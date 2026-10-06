"""Windows x64 Core Keeper fishing controller. Standard-library only.

The Python process attaches to the game's Mono runtime and loads the supplied
managed helper. No Cheat Engine, screen calibration, or mouse macro is used.
"""
import argparse
import ctypes as C
from ctypes import wintypes as W
import json
from pathlib import Path
import struct
import sys
import threading
import time
import tkinter as tk
from tkinter import ttk

ROOT = Path(__file__).resolve().parent
DLL = ROOT / "CoreKeeperAutoFishPython.dll"
STATUS = ROOT / "Core Keeper fishing status.txt"
LOG = ROOT / "Python fisher diagnostics.jsonl"
K = C.WinDLL("kernel32", use_last_error=True)
PTR = C.c_void_p
SIZE = C.c_size_t

class ProcessEntry(C.Structure):
    _fields_ = [("dwSize", W.DWORD), ("cntUsage", W.DWORD), ("th32ProcessID", W.DWORD),
                ("th32DefaultHeapID", SIZE), ("th32ModuleID", W.DWORD), ("cntThreads", W.DWORD),
                ("th32ParentProcessID", W.DWORD), ("pcPriClassBase", W.LONG),
                ("dwFlags", W.DWORD), ("szExeFile", W.WCHAR * 260)]

class ModuleEntry(C.Structure):
    _fields_ = [("dwSize", W.DWORD), ("th32ModuleID", W.DWORD), ("th32ProcessID", W.DWORD),
                ("GlblcntUsage", W.DWORD), ("ProccntUsage", W.DWORD), ("modBaseAddr", PTR),
                ("modBaseSize", W.DWORD), ("hModule", PTR), ("szModule", W.WCHAR * 256),
                ("szExePath", W.WCHAR * 260)]

def api(name, result, args):
    f = getattr(K, name); f.restype = result; f.argtypes = args
    return f

snapshot = api("CreateToolhelp32Snapshot", W.HANDLE, [W.DWORD, W.DWORD])
close = api("CloseHandle", W.BOOL, [W.HANDLE])
process_first = api("Process32FirstW", W.BOOL, [W.HANDLE, C.POINTER(ProcessEntry)])
process_next = api("Process32NextW", W.BOOL, [W.HANDLE, C.POINTER(ProcessEntry)])
module_first = api("Module32FirstW", W.BOOL, [W.HANDLE, C.POINTER(ModuleEntry)])
module_next = api("Module32NextW", W.BOOL, [W.HANDLE, C.POINTER(ModuleEntry)])
open_process = api("OpenProcess", W.HANDLE, [W.DWORD, W.BOOL, W.DWORD])
read_memory = api("ReadProcessMemory", W.BOOL, [W.HANDLE, PTR, PTR, SIZE, C.POINTER(SIZE)])
write_memory = api("WriteProcessMemory", W.BOOL, [W.HANDLE, PTR, PTR, SIZE, C.POINTER(SIZE)])
allocate = api("VirtualAllocEx", PTR, [W.HANDLE, PTR, SIZE, W.DWORD, W.DWORD])
release = api("VirtualFreeEx", W.BOOL, [W.HANDLE, PTR, SIZE, W.DWORD])
remote_thread = api("CreateRemoteThread", W.HANDLE, [W.HANDLE, PTR, SIZE, PTR, PTR, W.DWORD, PTR])
wait = api("WaitForSingleObject", W.DWORD, [W.HANDLE, W.DWORD])
flush = api("FlushInstructionCache", W.BOOL, [W.HANDLE, PTR, SIZE])
U = C.WinDLL("user32", use_last_error=True)
key_state = U.GetAsyncKeyState
key_state.restype = C.c_short
key_state.argtypes = [C.c_int]

def checked(value, description):
    if not value or value == PTR(-1).value:
        raise OSError(C.get_last_error(), description + ": " + C.FormatError(C.get_last_error()))
    return value

def entries(pid=None):
    handle = checked(snapshot(0x18 if pid else 2, pid or 0), "Snapshot")
    typ, first, nxt = (ModuleEntry, module_first, module_next) if pid else (ProcessEntry, process_first, process_next)
    try:
        entry = typ(); entry.dwSize = C.sizeof(typ)
        ok = first(handle, C.byref(entry))
        while ok:
            # Copy before the API overwrites its buffer.
            yield typ.from_buffer_copy(entry)
            ok = nxt(handle, C.byref(entry))
    finally:
        close(handle)

def game_pid():
    found = [p.th32ProcessID for p in entries() if p.szExeFile.lower() == "corekeeper.exe"]
    if len(found) != 1:
        raise RuntimeError(f"Expected one running CoreKeeper.exe; found {len(found)}.")
    return found[0]

def diagnostics(event, **values):
    row = {"time": time.strftime("%Y-%m-%d %H:%M:%S"), "event": event, **values}
    with LOG.open("a", encoding="utf-8") as out:
        out.write(json.dumps(row) + "\n")

class Game:
    def __init__(self, writable=False):
        if C.sizeof(PTR) != 8:
            raise RuntimeError("Use 64-bit Python.")
        self.pid = game_pid()
        self.handle = checked(open_process(0x43A if writable else 0x410, False, self.pid), "Open Core Keeper")
        self.writable = writable
        self.lock = threading.Lock()
        modules = list(entries(self.pid))
        mono = next((m for m in modules if m.szModule.lower() == "mono-2.0-bdwgc.dll"), None)
        if mono is None:
            close(self.handle)
            raise RuntimeError("Core Keeper's Mono runtime is not loaded.")
        self.base = mono.modBaseAddr
        self.exports = self.read_exports()
        diagnostics("attached", pid=self.pid, mono_base=hex(self.base), writable=writable)

    def read(self, address, length):
        buf = C.create_string_buffer(length); count = SIZE()
        checked(read_memory(self.handle, address, buf, length, C.byref(count)), "Read game memory")
        if count.value != length: raise RuntimeError("Incomplete game memory read")
        return buf.raw

    def write(self, address, data):
        data = bytes(data)
        buf = C.create_string_buffer(data); count = SIZE()
        checked(write_memory(self.handle, address, buf, len(data), C.byref(count)), "Write helper payload")
        if count.value != len(data): raise RuntimeError("Incomplete helper payload write")

    def u32(self, address): return struct.unpack("<I", self.read(address, 4))[0]
    def qword(self, address): return struct.unpack("<Q", self.read(address, 8))[0]
    def string(self, address, maximum=16384):
        data = bytearray()
        for i in range(maximum):
            b = self.read(address + i, 1)
            if b == b"\0": return data.decode("utf-8", errors="replace")
            data += b
        return data.decode("utf-8", errors="replace") + " [truncated]"

    def read_exports(self):
        pe = self.base + self.u32(self.base + 0x3C)
        if self.read(pe, 4) != b"PE\0\0": raise RuntimeError("Invalid Mono PE header")
        if struct.unpack("<H", self.read(pe + 24, 2))[0] != 0x20B:
            raise RuntimeError("Expected x64 Mono")
        export_rva, export_size = struct.unpack("<II", self.read(pe + 24 + 112, 8))
        table = self.base + export_rva
        count = self.u32(table + 24)
        funcs, names, ords = (self.base + self.u32(table + n) for n in (28, 32, 36))
        names_data = self.read(names, count * 4)
        ord_data = self.read(ords, count * 2)
        result = {}
        for i in range(count):
            name = self.string(self.base + struct.unpack_from("<I", names_data, i * 4)[0], 256)
            if name.startswith("mono_"):
                ordinal = struct.unpack_from("<H", ord_data, i * 2)[0]
                rva = self.u32(funcs + ordinal * 4)
                if export_rva <= rva < export_rva + export_size: continue
                result[name] = self.base + rva
        return result

    def invoke(self, method):
        if not self.writable: raise RuntimeError("Read-only attachment")
        with self.lock:
            return self._invoke(method)

    def _invoke(self, method):
        if not DLL.exists(): raise FileNotFoundError(DLL)
        names = ["mono_get_root_domain", "mono_thread_attach", "mono_domain_assembly_open",
                 "mono_assembly_get_image", "mono_class_from_name", "mono_class_get_method_from_name",
                 "mono_runtime_invoke", "mono_string_to_utf8", "mono_thread_detach"]
        for name in names:
            if name not in self.exports: raise RuntimeError("Mono export missing: " + name)
        block = checked(allocate(self.handle, None, 8192, 0x3000, 0x40), "Allocate helper call")
        slots = block + 4096
        strings = block + 4352
        payload = bytearray(); ptrs = []
        for value in (str(DLL), "CoreKeeperAutoFishPython", "Bridge", method):
            ptrs.append(strings + len(payload)); payload += value.encode("utf-8") + b"\0"
        if len(payload) > 3500: raise RuntimeError("Helper path too long")
        code = bytearray(b"\x48\x83\xec\x28")  # aligned Windows x64 shadow space
        jumps = []
        def imm(reg, value):
            code.extend({"rax": b"\x48\xb8", "rcx": b"\x48\xb9", "rdx": b"\x48\xba", "r8": b"\x49\xb8", "r9": b"\x49\xb9"}[reg] + struct.pack("<Q", value))
        def store(slot):
            imm("rdx", slots + slot * 8); code.extend(b"\x48\x89\x02")
        def load(reg, slot):
            imm(reg, slots + slot * 8)
            code.extend({"rcx": b"\x48\x8b\x09", "rdx": b"\x48\x8b\x12"}[reg])
        def call(name, stage, output=None, guard=True):
            imm("rax", self.exports[name]); code.extend(b"\xff\xd0")
            if output is not None: store(output)
            imm("rdx", slots + 0x70); code.extend(b"\xc7\x02" + struct.pack("<I", stage))
            if guard:
                code.extend(b"\x48\x85\xc0\x0f\x84"); jumps.append(len(code)); code.extend(b"\0" * 4)
        call("mono_get_root_domain", 1, 0)
        load("rcx", 0); call("mono_thread_attach", 2, 1)
        load("rcx", 0); imm("rdx", ptrs[0]); call("mono_domain_assembly_open", 3, 2)
        load("rcx", 2); call("mono_assembly_get_image", 4, 3)
        load("rcx", 3); imm("rdx", ptrs[1]); imm("r8", ptrs[2]); call("mono_class_from_name", 5, 4)
        load("rcx", 4); imm("rdx", ptrs[3]); imm("r8", 0); call("mono_class_get_method_from_name", 6, 5)
        load("rcx", 5); imm("rdx", 0); imm("r8", 0); imm("r9", slots + 0x50)
        call("mono_runtime_invoke", 7, 6)
        load("rcx", 6); call("mono_string_to_utf8", 8, 7)
        # Detach even when a lookup fails; unattached failure must skip detachment.
        cleanup = len(code)
        load("rcx", 1); code.extend(b"\x48\x85\xc9\x0f\x84")
        no_detach = len(code); code.extend(b"\0" * 4)
        imm("rax", self.exports["mono_thread_detach"]); code.extend(b"\xff\xd0")
        end = len(code); code.extend(b"\x31\xc0\x48\x83\xc4\x28\xc3")
        struct.pack_into("<i", code, no_detach, end - (no_detach + 4))
        for jump in jumps: struct.pack_into("<i", code, jump, cleanup - (jump + 4))
        thread = None; completed = False
        try:
            self.write(strings, payload); self.write(block, code)
            checked(flush(self.handle, block, len(code)), "Flush helper code")
            thread = checked(remote_thread(self.handle, None, 0, block, None, 0, None), "Start Mono helper call")
            result = wait(thread, 15000)
            if result != 0:
                raise RuntimeError("Mono call did not finish in 15 seconds. Stop here; do not retry until the game is restarted.")
            completed = True
            stage = self.u32(slots + 0x70)
            exception = self.qword(slots + 0x50)
            address = self.qword(slots + 7 * 8)
            if exception: raise RuntimeError(f"Mono raised an exception during {method} (stage {stage}, object {exception:#x}).")
            if not address: raise RuntimeError(f"Mono loading failed at stage {stage}: {names[max(0, stage - 1)]}.")
            message = self.string(address)
            diagnostics("managed_call", method=method, stage=stage, status=message)
            if "FAILED" in message or "ERROR=" in message: raise RuntimeError(message)
            return message
        finally:
            if thread: close(thread)
            # Never free code while the game's thread might still execute it.
            if completed or thread is None: release(self.handle, block, 0, 0x8000)

    def close(self):
        if self.handle: close(self.handle); self.handle = None

class App:
    def __init__(self):
        self.window = tk.Tk(); self.window.title("Core Keeper Python Fisher")
        self.game = None; self.busy = False; self.running = False; self.quit_after_stop = False
        ttk.Label(self.window, text="Equip a rod beside water. Start, then return to the game and aim at water. F11 stops while this window is running.", wraplength=520).pack(padx=20, pady=15)
        row = ttk.Frame(self.window); row.pack()
        self.start = ttk.Button(row, text="Start auto fishing", command=lambda: self.command("Enable")); self.start.pack(side="left", padx=5)
        self.stop = ttk.Button(row, text="Stop", command=lambda: self.command("Disable")); self.stop.pack(side="left", padx=5)
        self.text = tk.Text(self.window, width=76, height=15, wrap="word"); self.text.pack(padx=20, pady=15)
        self.text.insert("1.0", "Ready. This reads game state through a managed helper; Cheat Engine is not required.")
        self.window.protocol("WM_DELETE_WINDOW", self.closing)
        self.window.after(500, self.poll)
        self.window.after(100, lambda: self.command("Status"))

    def display(self, message):
        self.text.delete("1.0", "end"); self.text.insert("1.0", message)

    def command(self, method):
        if self.busy: return
        self.busy = True; self.start.config(state="disabled"); self.stop.config(state="disabled")
        self.display("Attaching and " + method.lower() + "... Please wait.")
        def worker():
            try:
                if self.game is None: self.game = Game(writable=True)
                message = self.game.invoke(method)
                if method == "Enable": self.running = True
                elif method == "Disable": self.running = False
                else: self.running = "Python ON;" in message
            except Exception as e:
                message = str(e); diagnostics("error", detail=message)
            self.window.after(0, lambda: self.done(message))
        threading.Thread(target=worker, daemon=True).start()

    def done(self, message):
        self.busy = False; self.start.config(state="normal"); self.stop.config(state="normal"); self.display(message)
        if self.quit_after_stop and not self.running:
            if self.game: self.game.close()
            self.window.destroy()

    def poll(self):
        if self.running and not self.busy and key_state(0x7A) & 0x8000:
            self.command("Disable")
        if self.running and not self.busy and STATUS.exists():
            try: self.display(STATUS.read_text(encoding="utf-8-sig"))
            except OSError: pass
        self.window.after(500, self.poll)

    def closing(self):
        if self.busy: return
        if self.running:
            self.quit_after_stop = True
            self.command("Disable")
            return  # Keep the window open until stop has completed.
        if self.game: self.game.close()
        self.window.destroy()

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--probe", action="store_true", help="Read-only process and Mono inspection")
    parser.add_argument("--enable", action="store_true")
    parser.add_argument("--disable", action="store_true")
    args = parser.parse_args()
    if args.probe or args.enable or args.disable:
        game = Game(writable=not args.probe)
        try:
            if args.probe: print(json.dumps({"pid": game.pid, "mono_base": hex(game.base), "mono_exports": len(game.exports)}))
            else: print(game.invoke("Disable" if args.disable else "Enable"))
        finally: game.close()
    else:
        App().window.mainloop()

if __name__ == "__main__":
    try: main()
    except Exception as exc:
        diagnostics("fatal", detail=str(exc)); print(str(exc), file=sys.stderr); sys.exit(1)

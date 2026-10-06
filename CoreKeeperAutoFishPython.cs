using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Reflection.Emit;
using HarmonyLib;
using UnityEngine;
using Unity.Mathematics;
using PlayerState;

namespace CoreKeeperAutoFishPython
{
    public static class Bridge
    {
        const string Id = "local.corekeeper.ce.autofish.input.python.v1";
        static readonly string LogFile = Path.Combine(Path.GetDirectoryName(typeof(Bridge).Assembly.Location), "Core Keeper fishing status.txt");
        static volatile bool enabled;
        static bool installed, pinned, charging, reelPulse;
        static float chargeStart, pulseEnd, nextCast, nextLog;
        static float2 point, aim, direction;
        static Pug.UnityExtensions.Direction facing;
        static long inputTicks, reads, casts, reels;
        static int caught, firstCaught = -1;
        static string action = "Disabled", error = "";
        static readonly FieldInfo SlotType = AccessTools.Field(typeof(PlayerController), "visuallyEquippedSlotType");

        public static void Tick() { System.Threading.Interlocked.Increment(ref inputTicks); }
        public static string Status()
        {
            return "Python " + (enabled ? "ON" : "OFF") + "; " + action + "; inputTicks=" + inputTicks + "; gameReads=" + reads + "; casts=" + casts + "; reels=" + reels + "; catchCounter=" + caught + "; catchDelta=" + (firstCaught < 0 ? 0 : caught - firstCaught) + (error == "" ? "" : "; ERROR=" + error);
        }
        static void Log() { try { File.WriteAllText(LogFile, DateTime.Now.ToString("O") + Environment.NewLine + Status()); } catch { } }

        public static string Enable()
        {
            try
            {
                if (!installed)
                {
                    DisableOlderHelpers();
                    MethodInfo update = AccessTools.DeclaredMethod(typeof(SendClientInputSystem), "OnUpdate");
                    if (update == null) throw new Exception("SendClientInputSystem.OnUpdate missing");
                    new Harmony(Id).Patch(update, prefix: new HarmonyMethod(typeof(Bridge), "Tick"), transpiler: new HarmonyMethod(typeof(Bridge), "Transpile"));
                    installed = true;
                }
                pinned = charging = reelPulse = false;
                nextCast = nextLog = 0;
                inputTicks = reads = casts = reels = 0;
                firstCaught = -1;
                error = "";
                action = "Waiting for focused game, equipped rod, and water aim";
                enabled = true;
            }
            catch (Exception e)
            {
                enabled = false; installed = false;
                try { new Harmony(Id).UnpatchSelf(); } catch { }
                error = e.ToString(); action = "FAILED";
            }
            Log(); return Status();
        }

        static void DisableOlderHelpers()
        {
            foreach (string name in new[] { "CoreKeeperAutoFish.Bridge", "CoreKeeperAutoFishV2.Bridge" })
                foreach (var assembly in AppDomain.CurrentDomain.GetAssemblies())
                {
                    var type = assembly.GetType(name, false);
                    if (type != null) type.GetMethod("Disable").Invoke(null, null);
                }
        }

        public static string Disable()
        {
            enabled = false;
            try { if (installed) new Harmony(Id).UnpatchSelf(); installed = false; action = "Disabled; input hook removed"; }
            catch (Exception e) { error = e.Message; action = "Disabled; unpatch failed"; }
            Log(); return Status();
        }

        // Runs on the game's main thread, just before input is copied into ECS.
        public static void Apply(ref ClientInput input, PlayerController player)
        {
            if (!enabled) return;
            float now = Time.realtimeSinceStartup;
            try
            {
                if (!Application.isFocused) { action = "Paused: game not focused"; return; }
                if (player == null || !player.isLocal) { action = "Waiting for local player"; return; }
                if (SlotType == null || (PlayerEquipment.EquipmentSlotType)SlotType.GetValue(player) != PlayerEquipment.EquipmentSlotType.FishingRodSlot) { action = "Paused: equip a fishing rod"; return; }
                if (SendClientInputSystem.PlayerInputBlocked() || SendClientInputSystem.PlayerInteractionBlocked()) { action = "Paused: game input blocked"; return; }
                if (math.lengthsq(input.movementDirection) > 0.01f) { action = "Paused: moving"; return; }
                var state = EntityUtility.GetComponentData<PlayerStateCD>(player.entity, player.world);
                if (state.isStateLocked || state.HasAnyState(PlayerStateEnum.Death | PlayerStateEnum.Inactive | PlayerStateEnum.Teleporting | PlayerStateEnum.Sleep)) { action = "Paused: player state"; return; }
                var fish = EntityUtility.GetComponentData<FishingStateCD>(player.entity, player.world);
                reads++;
                caught = fish.caughtFishCounter;
                if (firstCaught < 0) firstCaught = caught;
                if (!pinned)
                {
                    point = input.mouseOrJoystickWorldPoint; aim = input.aimDirection;
                    direction = input.targetingDirection; facing = input.facingDirection;
                    pinned = true;
                }
                input.mouseOrJoystickWorldPoint = point;
                input.aimDirection = aim; input.targetingDirection = direction; input.facingDirection = facing;
                input.useFishingMiniGame = false;
                input.SetButtonState(CommandInputButtonStateNames.SecondInteract_HeldDown, false);
                input.SetButtonState(CommandInputButtonStateNames.SecondInteract_Pressed, false);
                input.SetButtonState(CommandInputButtonStateNames.SecondInteract_Released, false);

                if (reelPulse)
                {
                    if (now < pulseEnd)
                    {
                        input.SetButtonState(CommandInputButtonStateNames.SecondInteract_HeldDown, true);
                        action = "Reeling"; return;
                    }
                    input.SetButtonState(CommandInputButtonStateNames.SecondInteract_Released, true);
                    reelPulse = false; nextCast = now + 0.8f;
                    action = "Waiting for catch animation"; return;
                }
                if (charging)
                {
                    if (now - chargeStart < 0.6f)
                    {
                        input.SetButtonState(CommandInputButtonStateNames.SecondInteract_HeldDown, true);
                        action = "Charging cast"; return;
                    }
                    input.SetButtonState(CommandInputButtonStateNames.SecondInteract_Released, true);
                    charging = false; nextCast = now + 2f;
                    action = "Casting"; return;
                }
                if (state.HasAnyState(PlayerStateEnum.Fishing))
                {
                    if (fish.pullUpTimer.isRunning) { action = "Waiting for catch animation"; return; }
                    if (fish.castTimer.isRunning || fish.throwTimer.isRunning) { action = "Waiting for bobber"; return; }
                    if (fish.isSuccessfullyFishing && fish.fishIsNibbling)
                    {
                        input.SetButtonState(CommandInputButtonStateNames.SecondInteract_HeldDown, true);
                        input.SetButtonState(CommandInputButtonStateNames.SecondInteract_Pressed, true);
                        reelPulse = true; pulseEnd = now + 0.12f; reels++;
                        action = "Bite detected; reeling"; return;
                    }
                    action = fish.isSuccessfullyFishing ? "Waiting for bite (reading game state)" : "Cast did not reach valid water";
                    return;
                }
                if (now >= nextCast)
                {
                    input.SetButtonState(CommandInputButtonStateNames.SecondInteract_HeldDown, true);
                    input.SetButtonState(CommandInputButtonStateNames.SecondInteract_Pressed, true);
                    charging = true; chargeStart = now; casts++;
                    action = "Starting automatic cast";
                }
                else action = "Waiting before recast";
            }
            catch (Exception e) { enabled = false; error = e.ToString(); action = "Stopped after game-read error"; }
            finally { if (now >= nextLog) { nextLog = now + 0.5f; Log(); } }
        }

        public static IEnumerable<CodeInstruction> Transpile(IEnumerable<CodeInstruction> instructions, MethodBase __originalMethod)
        {
            var code = instructions.ToList();
            var locals = __originalMethod.GetMethodBody().LocalVariables;
            int inputIndex = locals.First(v => v.LocalType == typeof(ClientInput)).LocalIndex;
            var inputAddress = code.First(c => (c.opcode == OpCodes.Ldloca || c.opcode == OpCodes.Ldloca_S) && LocalIndex(c.operand) == inputIndex);
            // The mouse target is the last input field populated before ECS serialization.
            int anchor = code.FindLastIndex(c => c.opcode == OpCodes.Stfld && c.operand is FieldInfo && ((FieldInfo)c.operand).DeclaringType == typeof(ClientInput) && ((FieldInfo)c.operand).Name == "mouseOrJoystickWorldPoint");
            if (anchor < 0) throw new Exception("Unsupported input layout: mouse target assignment missing");
            MethodInfo main = AccessTools.PropertyGetter(typeof(Manager), "main");
            MethodInfo player = AccessTools.PropertyGetter(typeof(Manager), "player");
            if (main == null || player == null) throw new Exception("Local player accessors missing");
            code.InsertRange(anchor + 1, new[] {
                new CodeInstruction(inputAddress.opcode, inputAddress.operand),
                new CodeInstruction(OpCodes.Call, main), new CodeInstruction(OpCodes.Callvirt, player),
                new CodeInstruction(OpCodes.Call, AccessTools.Method(typeof(Bridge), "Apply"))
            });
            return code;
        }
        static int LocalIndex(object value)
        {
            if (value is LocalBuilder) return ((LocalBuilder)value).LocalIndex;
            if (value is LocalVariableInfo) return ((LocalVariableInfo)value).LocalIndex;
            return Convert.ToInt32(value);
        }
    }
}



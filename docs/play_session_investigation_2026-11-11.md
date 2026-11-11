# Play Session Investigation — 2026-11-11

## Summary

Tested the `current_state` + prompt constraint changes in a live play session. Results: one issue fixed, three remaining.

---

## ✅ Fixed: Narration metadata leak

The narration model no longer weaves round numbers into prose. Round 0 narration begins:

> "The marketplace transforms into a hellish labyrinth of roaring flames and choking gray vapor..."

Previously it would have said "under the Zeroth Round of crisis." The metadata ignore constraints are working.

---

## ⚠️ Issue 1: Location conditions not updating despite narrative describing changes

**Symptom:** After Round 1, the narration describes the fire receding ("the roaring intensity of the fire begins to recede, beaten down until the raging blaze softens into a contained but still dangerous battle... the last flame flickers defiantly"). But at Round 2 and 3 the CLI still shows:

```
Conditions: on_fire, smoky, chaotic
```

Unchanged from Round 0.

**Root cause:** The resolution LLM produces location effects but they don't remove or modify the core conditions (`on_fire`, `chaotic`). It adds character memory entries and inventory items, but the location conditions list stays the same or gets appended to rather than updated. The constraint "Every state change described in your narrative MUST have a corresponding effect" is present but the LLM treats it as a suggestion among many, not a binding rule.

**Evidence:** The parse output shows location effects were produced:
```
npc_garrick: partial_success —
  → location:marketplace —
npc_mira: critical_success —
  → location:marketplace —
pc_1: partial_success —
  → location:marketplace —
```
But the conditions at Round 2 are still `on_fire, smoky, chaotic` — the effects didn't change them meaningfully.

---

## ⚠️ Issue 2: LLM putting `current_state` in effect changes

**Symptom:** The elders_hall Round 1 resolution response includes:

```json
"changes": {
    "description": "A sturdy stone building where the village council meets, now functioning as a crowded evacuation staging area.",
    "current_state": "crowded; evacuation_in_progress",
    "environment": {
        "conditions": ["crowded", "evacuation_in_progress"]
    }
}
```

The LLM thinks `current_state` is a writable field because it appears in the payload. It's not a real field on `LocationNode` — the effect applier would set it as a stray key on the location data dict, which doesn't break anything but is meaningless noise.

**Fix needed:** Tell the resolution model that `current_state` is read-only context, not a field to write to in effects.

---

## ❌ Issue 3: Resolution LLM JSON truncation → silent fallback

**Symptom:** Round 2 marketplace resolution:

```
[DM] Calling LLM (model=qwen3.8-flash)... done (8085 chars)
[DM] LLM failed (JSONDecodeError: Unterminated string starting at: line 240 column 5 (char 8084)) — fallback
```

The resolution model produced 8085 chars of JSON with an unterminated string. It fell back to rule-based resolution, meaning **no LLM effects were applied** for marketplace Round 2. The player saw narration (from the separate narration model call) but the game state didn't reflect any resolution decisions.

**Root cause:** With 3 characters acting simultaneously, the LLM response grows large. The cheap/fast model (qwen3.8-flash) is prone to JSON formatting errors in long outputs. No retry before fallback.

---

## ✅ Working: `current_state` in payload

The payload correctly includes `current_state`:

```json
"current_state": "The central gathering place of Oakhaven. A stone well sits in the middle, surrounded by benches and a notice board. [Current state: smoky]"
```

And the elders_hall description was successfully updated by a previous effect:

```
"description": "A sturdy stone building where the village council meets, now functioning as a crowded evacuation staging area."
```

This proves the effect pipeline works when the LLM emits the right changes.

---

## Remaining Work

| Issue | Severity | Fix Approach |
|-------|----------|-------------|
| Conditions not updating | High | Move the "narrative→effects" rule from a constraint line to a dedicated task step, making it impossible to miss |
| `current_state` in effect changes | Medium | Add prompt instruction: "`current_state` is read-only context, do NOT include it in effect changes" |
| JSON truncation fallback | High | Add retry with reduced max_tokens or stream+repair before falling back to rule-based |

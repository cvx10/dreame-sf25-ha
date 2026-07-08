# Dashboard recipe — Cellier compost icon + SF25 pop-up

This is the Lovelace setup used on the **Pinsons** dashboard to show the SF25 in
the **Cellier** card: a `mdi:compost` chip that opens a Bubble Card pop-up with a
product photo and the live sensors.

Requires (all via HACS): **Bubble Card**, **Mushroom**, **card-mod**.

## 1. Compost chip (added to the Cellier `mushroom-chips-card`)

```yaml
- type: template
  entity: sensor.burnthemall_status
  icon: mdi:compost
  icon_color: >-
    {{ 'green' if is_state('sensor.burnthemall_run_state','running')
       else ('amber' if is_state('sensor.burnthemall_run_state','paused')
       else 'grey') }}
  tap_action:
    action: navigate
    navigation_path: '#compost-sf25'
```

The icon is green while a cycle runs, amber when paused, grey when idle.

## 2. Bubble Card pop-up (placed alongside the other pop-ups in the view)

> **IMPORTANT — full-width layout.** Bubble Card lays the pop-up content `cards:`
> out in a **12-column grid** (same engine as a `sections` view), so a card with
> no span defaults to ~half width and two cards sit *side by side*. With
> `popup_mode: fit-content` that collapsed the whole pop-up to a ~90 px strip
> pinned to the bottom of the screen, clipping everything. The fix is to give
> every top-level content card `grid_options: {columns: 12}` so each one takes a
> full row and the pop-up grows to its natural height.

```yaml
- type: custom:bubble-card
  card_type: pop-up
  hash: '#compost-sf25'
  name: BurnThemAll
  icon: mdi:compost
  button_type: name
  show_header: false
  slide_to_close_distance: '100'
  popup_mode: fit-content
  cards:
    # Header — current state (run_state + mode based, so it survives restarts;
    # the cooling phase comes from the derived Activity sensor, v0.6.1+)
    - type: custom:mushroom-template-card
      grid_options: {columns: 12}   # full row — without this it renders half-width
      primary: >-
        {% set r = states('sensor.burnthemall_run_state') %}
        {% set m = states('sensor.burnthemall_mode') %}
        {% set a = states('sensor.burnthemall_activity') %}
        {% if a == 'cooling' %}Refroidissement
        {% elif r == 'running' %}{{ 'Nettoyage en cours' if m == 'cleaning' else 'Séchage en cours' }}
        {% elif r == 'paused' %}En pause
        {% elif r in ['unknown','unavailable'] %}Indisponible
        {% else %}Au repos{% endif %}
      secondary: >-
        {% set r = states('sensor.burnthemall_run_state') %}
        {% set a = states('sensor.burnthemall_activity') %}
        {% set e = states('sensor.burnthemall_energy') %}
        {% set tp = states('sensor.burnthemall_temperature') %}
        {% if a == 'cooling' %}{{ ((e ~ ' Wh') if e not in ['unknown','unavailable'] else '')
          ~ (' · ' if (e not in ['unknown','unavailable'] and tp not in ['unknown','unavailable']) else '')
          ~ ((tp ~ ' °C') if tp not in ['unknown','unavailable'] else '') }}
        {% elif r in ['running','paused'] %}{{ (e ~ ' Wh') if e not in ['unknown','unavailable'] else '' }}
        {% else %}Prêt à démarrer{% endif %}
      icon: mdi:compost
      icon_color: >-
        {% set r = states('sensor.burnthemall_run_state') %}
        {{ 'green' if r == 'running' else ('amber' if r == 'paused' else 'grey') }}
      layout: horizontal
      fill_container: true
      tap_action: {action: none}
    # Progress bar — a card-mod linear-gradient fills to the cycle %. Shown
    # only while a cycle is active (run_state not stopped/unknown/unavailable)
    # so an idle device doesn't show a dead "0%" bar. The secondary line packs
    # the remaining time AND the estimated finish into one sentence — each
    # datum appears exactly once in the popup (no separate tiles).
    - type: conditional
      grid_options: {columns: 12}
      conditions:
        - {entity: sensor.burnthemall_run_state, state_not: stopped}
        - {entity: sensor.burnthemall_run_state, state_not: unknown}
        - {entity: sensor.burnthemall_run_state, state_not: unavailable}
      card:
        type: custom:mushroom-template-card
        primary: >-
          {% set a = states('sensor.burnthemall_activity') %}
          {% set p = states('sensor.burnthemall_cycle_progress')|int(0) %}
          {% if a == 'cooling' %}Refroidissement{% else %}Progression — {{ p }}%{% endif %}
        secondary: >-
          {% set a = states('sensor.burnthemall_activity') %}
          {% set r = states('sensor.burnthemall_run_state') %}
          {% set t = states('sensor.burnthemall_time_remaining')|int(0) %}
          {% set dur = (t//60 ~ 'h' ~ '%02d'|format(t%60)) if t >= 60 else (t ~ ' min') %}
          {% if a == 'cooling' %}{% set tp = states('sensor.burnthemall_temperature') %}Cycle terminé · en refroidissement{{ (' · ' ~ tp ~ ' °C') if tp not in ['unknown','unavailable'] else '' }}
          {% elif r == 'running' %}Encore {{ dur }} · fin à
          {{ (as_timestamp(now()) + t*60) | timestamp_custom('%H:%M', true) }}
          {% else %}En pause · encore {{ dur }}{% endif %}
        icon: "{{ 'mdi:snowflake' if is_state('sensor.burnthemall_activity','cooling') else 'mdi:progress-clock' }}"
        icon_color: >-
          {% set a = states('sensor.burnthemall_activity') %}
          {% set r = states('sensor.burnthemall_run_state') %}
          {{ 'blue' if a == 'cooling' else ('green' if r == 'running' else 'amber') }}
        layout: horizontal
        fill_container: true
        tap_action: {action: none}
        card_mod:
          style: |
            {% set p = states('sensor.burnthemall_cycle_progress')|int(0) %}
            ha-card {
              border: none; box-shadow: none; border-radius: 14px;
              background: linear-gradient(to right,
                rgba(var(--rgb-green), 0.30) {{ p }}%,
                rgba(128,128,128,0.12) {{ p }}%);
            }
    # Lid status only — and only when NOT running. During a cycle the lid is
    # necessarily closed, so showing it would be noise. The `conditional` card
    # hides the whole row while run_state == running. (The lid-alert binary
    # sensor is intentionally omitted: it duplicates the lid open/closed state.)
    - type: conditional
      grid_options: {columns: 12}
      conditions:
        - entity: sensor.burnthemall_run_state
          state_not: running
      card:
        type: entities
        card_mod: {style: "ha-card { border: none; box-shadow: none; }\n"}
        entities:
          - {entity: binary_sensor.burnthemall_lid, name: Couvercle}
```

## Notes
- **Display-only / no controls.** Every card uses `tap_action: {action: none}`.
  The integration is read-only (`PLATFORMS = [SENSOR, BINARY_SENSOR]`, no
  switch/button/select), so there is no pause/stop/start control to expose — the
  command channel has never been reverse-engineered. Nothing in this pop-up can
  send a command to the device.
- The popup is intentionally compact: a product photo was tried but removed —
  it took too much vertical space and added no information. **Each datum appears
  exactly once**: state + mode in the header primary, heater energy (Wh) in the header
  secondary, % in the progress-bar primary, remaining time + finish in the
  progress-bar secondary, lid in its own row when idle. A 4-tile detail grid
  (temp/time/finish/mode) was tried and removed — it duplicated every one of
  those values.
- Entity IDs assume the device is named **BurnThemAll**. Adjust the
  `burnthemall_*` slugs if your device has a different name.
- The header, progress bar and chip deliberately derive from `run_state` +
  `mode` + `time_remaining` (which `RestoreSensor` restores on startup) rather
  than the derived `Estimated Finish` sensor. The `Activity` sensor is used
  only for the **cooling** branch (v0.6.1+): after drying ends the device keeps
  `run_flag=1` with `time_remaining=0` and an unrecognised mode code, which
  Activity maps to `cooling`. Activity is restore-backed too, so a restart
  mid-cooling keeps the label.
- During cooling the header secondary shows the cycle's total energy and the
  new tentative Temperature sensor (3/2); the progress bar swaps to a snowflake
  with "Cycle terminé · en refroidissement".
- The progress-bar fill is a `card-mod` `linear-gradient` whose stop position is
  the `cycle_progress` percentage (`|int(0)` guards the `unknown` case → 0%).

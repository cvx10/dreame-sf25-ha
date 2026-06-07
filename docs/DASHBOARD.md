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
    - type: picture
      image: >-
        https://oss.iot.dreame.tech/pub/pic/000000/ali_dreame/null/7b9845a3c5c47e1da3e203507b1b1a4d20260302072013.png
      card_mod:
        style: |
          ha-card { border: none; box-shadow: none; background: none; }
          img { border-radius: 14px; }
    # Header — current state (run_state + mode based, so it survives restarts)
    - type: custom:mushroom-template-card
      primary: >-
        {% set r = states('sensor.burnthemall_run_state') %}
        {% set m = states('sensor.burnthemall_mode') %}
        {% if r == 'running' %}{{ 'Nettoyage en cours' if m == 'cleaning' else 'Séchage en cours' }}
        {% elif r == 'paused' %}En pause
        {% elif r in ['unknown','unavailable'] %}Indisponible
        {% else %}Au repos{% endif %}
      secondary: >-
        {% set r = states('sensor.burnthemall_run_state') %}
        {% if r == 'running' %}{{ states('sensor.burnthemall_temperature') }}°C ·
        {{ states('sensor.burnthemall_time_remaining') }} min
        {% elif r == 'paused' %}En pause · {{ states('sensor.burnthemall_time_remaining') }} min
        {% else %}Prêt{% endif %}
      icon: mdi:compost
      icon_color: >-
        {% set r = states('sensor.burnthemall_run_state') %}
        {{ 'green' if r == 'running' else ('amber' if r == 'paused' else 'grey') }}
      layout: horizontal
      fill_container: true
      tap_action: {action: none}
    # Progress bar — a card-mod linear-gradient fills to the cycle %.
    - type: custom:mushroom-template-card
      primary: "{% set p = states('sensor.burnthemall_cycle_progress')|int(0) %}Progression — {{ p }}%"
      secondary: >-
        {% set r = states('sensor.burnthemall_run_state') %}
        {% if r == 'running' %}Fin estimée à
        {{ (as_timestamp(now()) + (states('sensor.burnthemall_time_remaining')|int(0))*60) | timestamp_custom('%H:%M', true) }}
        {% else %}Aucun cycle en cours{% endif %}
      icon: mdi:progress-clock
      icon_color: >-
        {% set r = states('sensor.burnthemall_run_state') %}
        {{ 'green' if r == 'running' else 'grey' }}
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
    - type: entities
      card_mod: {style: "ha-card { border: none; box-shadow: none; }\n"}
      entities:
        - {entity: sensor.burnthemall_activity, name: État}
        - {entity: sensor.burnthemall_mode, name: Mode}
        - {entity: sensor.burnthemall_time_remaining, name: Temps restant}
        - {entity: sensor.burnthemall_estimated_finish, name: Fin estimée}
        - {entity: sensor.burnthemall_temperature, name: Température}
        - {entity: binary_sensor.burnthemall_lid, name: Couvercle}
        - {entity: binary_sensor.burnthemall_lid_alert, name: Alerte couvercle}
```

## Notes
- The photo is the Dreame CDN product image for `dreame.fwd.u2527`. It loads
  remotely; if the CDN URL ever changes, download the image into
  `/config/www/sf25.png` and use `image: /local/sf25.png` instead.
- Entity IDs assume the device is named **BurnThemAll**. Adjust the
  `burnthemall_*` slugs if your device has a different name.
- The header, progress bar and chip deliberately derive from `run_state` +
  `mode` + `time_remaining` (which `RestoreSensor` restores on startup) rather
  than the derived `Activity` / `Estimated Finish` sensors. Those derived
  sensors need a fresh `run_flag` push (only sent on a state change), so right
  after a restart mid-cycle they read `unknown` until the next transition. The
  restore-backed properties keep the popup correct immediately. `Activity` and
  `Estimated Finish` still appear in the entities list.
- The progress-bar fill is a `card-mod` `linear-gradient` whose stop position is
  the `cycle_progress` percentage (`|int(0)` guards the `unknown` case → 0%).

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
    - type: custom:mushroom-template-card
      primary: "{{ states('sensor.burnthemall_status') | capitalize }}"
      secondary: >-
        {% if is_state('sensor.burnthemall_run_state','running') %}Mode
        {{ states('sensor.burnthemall_mode') }} ·
        {{ states('sensor.burnthemall_temperature') }}°C{% else %}En veille{% endif %}
      icon: mdi:compost
      icon_color: >-
        {{ 'green' if is_state('sensor.burnthemall_run_state','running')
           else ('amber' if is_state('sensor.burnthemall_run_state','paused')
           else 'grey') }}
      layout: horizontal
      fill_container: true
      tap_action: {action: none}
    - type: entities
      card_mod: {style: "ha-card { border: none; box-shadow: none; }\n"}
      entities:
        - {entity: sensor.burnthemall_run_state, name: Exécution}
        - {entity: sensor.burnthemall_mode, name: Mode}
        - {entity: sensor.burnthemall_cycle_progress, name: Progression}
        - {entity: sensor.burnthemall_time_remaining, name: Temps restant}
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

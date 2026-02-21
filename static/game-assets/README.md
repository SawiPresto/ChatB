Asset guide for SawiPresto Revenge Mini App

Recommended formats
- Character and equipment: PNG with transparent background
- UI icons: SVG
- Large background images: WebP

Suggested files
- characters/sawipresto-base.png
- backgrounds/forest-battle.webp
- enemies/enemy-scout.png
- weapons/bamboo-spear.png
- weapons/shadow-blade.png
- weapons/quantum-cleaver.png
- pets/neko-drone.png
- pets/turbo-hammy.png
- skins/ronin-jacket.png

Recommended sizes
- Character base/layer: 1024x1024
- Equipment: 512x512
- Keep transparent margins consistent across layers for proper alignment.

Custom assets
- Replace files with the same names to update visuals immediately.
- Or edit item asset paths in app.py (`GAME_SHOP_ITEMS`) and env vars:
  - `GAME_CHARACTER_BASE_ASSET`
  - `GAME_BATTLE_BG_ASSET`
  - `GAME_ENEMY_BASE_ASSET`

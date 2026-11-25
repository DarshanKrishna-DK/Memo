# Third-party assets (3D museum)

Local copies, so the museum does not depend on third-party CDNs. Copied from MedSim
(`D:/Med-Sim/public/assets`, see its CREDITS.md) by the web-3d agent.

| File | Source | Licence |
|---|---|---|
| characters/Xbot.glb | three.js examples, `examples/models/gltf/Xbot.glb` (Mixamo). Used only as the animation source (idle / walk / run), never rendered | Mixamo / Adobe, as redistributed with the three.js examples |
| characters/male-kurta.glb | Built in Blender for MedSim from the three.js examples `readyplayer.me.glb` (Ready Player Me avatar): suit details removed, cloth top + trousers, fitted haircut. Memo trims the top at the hip at runtime (a shirt) | Ready Player Me avatar terms, as redistributed with the three.js examples (MIT repository) |
| characters/female-saree.glb | Built in Blender for MedSim on TalkingHead's `avatars/brunette-t.glb` (Ready Player Me avatar, https://github.com/met4citizen/TalkingHead): saree skirt with pleats, border, pallu over the shoulder, blouse, bindi, bangles | **CC BY-NC 4.0** (non-commercial use; attribution: Ready Player Me / TalkingHead) |

Everything else in the museum (building, doors, lift, theater, signage, robots, textures,
the QR code) is generated procedurally in code under `src/world/`.

Note: the saree body (player woman and Grandma) inherits CC BY-NC 4.0. Replace it with a
commercially licensed base mesh before any commercial launch.

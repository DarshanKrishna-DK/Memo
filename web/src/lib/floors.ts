/**
 * The museum's FIXED calendar, the same for every family and every public link (mirrors backend core/museum.py):
 * 2002 is the ground floor (level 0, beside the lobby); each later year is one floor up. The 3D world and the lift
 * use `level` (year - 2002); people see the floor number (year - 2001): 2002 = "Ground" (floor 1), 2026 = "Floor 25".
 * Years before 2002 are basements (level < 0): 2001 = "Basement 1". Floors go up to the current year + 1.
 */
export const GROUND_YEAR = 2002;

export const levelOfYear = (year: number) => year - GROUND_YEAR;
export const yearOfLevel = (level: number) => GROUND_YEAR + level;
/** The number people see: 2002 -> 1 (ground), 2026 -> 25. */
export const floorNumberOfLevel = (level: number) => level + 1;

/** "Ground" / "Floor 25" / "Basement 1". */
export function floorLabel(level: number): string {
  if (level === 0) return 'Ground';
  return level > 0 ? `Floor ${floorNumberOfLevel(level)}` : `Basement ${-level}`;
}

/** Short lift-indicator form: "G" / "25" / "B1". */
export function floorShort(level: number): string {
  if (level === 0) return 'G';
  return level > 0 ? String(floorNumberOfLevel(level)) : `B${-level}`;
}

/** "Ground · 2002" / "Floor 25 · 2026". */
export const floorWithYear = (level: number) => `${floorLabel(level)} · ${yearOfLevel(level)}`;

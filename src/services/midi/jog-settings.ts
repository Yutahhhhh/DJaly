export const JOG_DEFAULT = 0.1;
export const JOG_MIN = 0.005;
export const JOG_MAX = 0.25;
export function jogSetting(value:number,version:string|null):number {
  if(!Number.isFinite(value) || value<=0) return JOG_DEFAULT;
  // Explicitly migrate large saved values too: changing only the fallback
  // leaves the live device using the exact sensitivity the user rejected.
  if (version === "3" && value === 0.05) return JOG_DEFAULT;
  return Math.max(JOG_MIN,Math.min(version==="3" || version==="4"?JOG_MAX:JOG_DEFAULT,value));
}

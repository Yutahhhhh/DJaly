/** Keep drive and UNC roots intact when navigating native filesystem paths. */
export function pathBreadcrumbs(path: string): { name: string; path: string }[] {
  if (!path) return [];
  const separator = path.includes("\\") ? "\\" : "/";
  const normalized = path.replace(/\\/g, "/");
  const root = normalized.match(/^\/\/[^/]+\/[^/]+\/?|^[A-Za-z]:\/|^\//)?.[0] ?? "";
  let accumulated = root.replace(/\/$/, "");
  const native = (value: string) => value.replace(/\//g, separator);
  const crumbs = root ? [{ name: native(root), path: native(root.endsWith("/") ? root : `${root}/`) }] : [];
  for (const part of normalized.slice(root.length).split("/").filter(Boolean)) {
    accumulated = accumulated ? `${accumulated}/${part}` : root ? `/${part}` : part;
    crumbs.push({ name: part, path: native(accumulated) });
  }
  return crumbs;
}

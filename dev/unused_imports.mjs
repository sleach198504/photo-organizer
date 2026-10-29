// Lists imported names a UI module never uses. Run: node dev/unused_imports.mjs
import { readdirSync, readFileSync } from "node:fs";
import { join, relative } from "node:path";

const root = "app/web/static/js";
const walk = (dir) =>
  readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    if (entry.isDirectory()) return entry.name === "vendor" ? [] : walk(join(dir, entry.name));
    return entry.name.endsWith(".js") ? [join(dir, entry.name)] : [];
  });

let found = 0;
for (const file of walk(root)) {
  const source = readFileSync(file, "utf8");
  for (const match of source.matchAll(/import\s*\{([^}]+)\}\s*from/g)) {
    for (const raw of match[1].split(",")) {
      const name = raw.trim().split(/\s+as\s+/).pop();
      if (!name) continue;
      const uses = (source.match(new RegExp(`\\b${name}\\b`, "g")) ?? []).length;
      if (uses < 2) {
        console.log(`${relative(root, file)}: unused import ${name}`);
        found += 1;
      }
    }
  }
}
console.log(found ? `${found} unused` : "no unused imports");
process.exit(found ? 1 : 0);

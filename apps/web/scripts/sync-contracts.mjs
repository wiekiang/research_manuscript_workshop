// Copy generated contracts (required copy + state machine) from contracts/schemas into the web app.
import { copyFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const schemas = resolve(here, "../../../contracts/schemas");
for (const name of ["copy.json", "state_machine.json"]) {
    copyFileSync(resolve(schemas, name), resolve(here, "../src/lib", name));
    console.log(`synced ${name}`);
}

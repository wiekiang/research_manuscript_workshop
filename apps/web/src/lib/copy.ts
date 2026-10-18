/**
 * Required product copy (spec §1), synced byte-for-byte from contracts/schemas/copy.json by `npm run sync:contracts`.
 * Never paraphrase these strings in components; import them from here.
 */
import copyJson from "./copy.json";

export const COPY = copyJson as {
    home_headline: string;
    home_subhead: string;
    responsibility_message: string;
    responsibility_version: string;
    literature_setup_message: string;
    provider_connection_template: string;
    coverage_template: string;
    contribution_workspace_title: string;
    contribution_workspace_fields: string[];
    final_approval_declaration: string;
    submission_ready_definition: string;
};

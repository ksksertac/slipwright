import { Empty } from "../components/ui";

export function AgentStandardsTab({ role, domain }: { role: string; domain: string }) {
  return (
    <Empty title="Standards">
      The {role} agent reads the <code>{domain}</code> standards. Editing them here arrives with
      T9.6.
    </Empty>
  );
}

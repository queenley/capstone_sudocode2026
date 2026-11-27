"use client";
// The admin sections whose component also serves the developer workspace (features/developer/workspace.tsx), so it
// takes the token and the notice as props: here each one reads them from the admin workspace. One export per route
// (app/admin/<slug>/page.tsx).
import { useState } from "react";
import AdminTools from "./admin-tools";
import { useAdmin } from "./admin-context";
import EvaluationDashboard from "./evaluation-dashboard";
import FaqAdmin from "./faq-admin";
import ImprovementAdmin from "./improvement-admin";
import KnowledgeGaps from "./knowledge-gaps";
import MarketCards from "./market-cards";
import PoliciesAdmin from "./policies-admin";
import SkillsAdmin from "./skills-admin";

/** /admin/kien-thuc: questions the documents did not answer, beside the FAQ they become. */
export function KnowledgeSection() {
  const { token } = useAdmin();
  const [faqAdded, setFaqAdded] = useState(0);
  return (
    <div className="sl-columns ad-knowledge">
      <KnowledgeGaps token={token} onFaqCreated={() => setFaqAdded((count) => count + 1)} />
      <FaqAdmin token={token} refresh={faqAdded} />
      <MarketCards token={token} />
    </div>
  );
}

export function PoliciesSection() {
  const { token, setNotice } = useAdmin();
  return <PoliciesAdmin token={token} onNotice={setNotice} />;
}

export function SkillsSection() {
  const { token, setNotice } = useAdmin();
  return <SkillsAdmin token={token} onNotice={setNotice} />;
}

export function ImprovementSection() {
  const { token, setNotice } = useAdmin();
  return <ImprovementAdmin token={token} onNotice={setNotice} />;
}

export function EvaluationSection() {
  const { token, setNotice } = useAdmin();
  return <EvaluationDashboard token={token} onNotice={setNotice} />;
}

export function StaffSection() {
  const { token, setNotice } = useAdmin();
  return <AdminTools token={token} onError={setNotice} />;
}

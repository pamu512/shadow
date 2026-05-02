/** Agent sometimes prints fake client-side “tool calls”; hide those from the sandbox UI. */
const HALLUCINATED_TOOL = /(build_user_behavioral_profile_tool|analyze_ato_risk_tool)\s*\(/i

export function isHallucinatedAgentToolSnippet(code: string, lang: string): boolean {
  const l = (lang || '').toLowerCase()
  if (l !== 'python' && l !== 'py') return false
  return HALLUCINATED_TOOL.test(code)
}

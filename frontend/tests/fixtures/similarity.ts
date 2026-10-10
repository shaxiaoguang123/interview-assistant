// Phase 1A/1B fixtures have no similar relations; the new review API is independent.
export function emptySimilarityResponse(path: string): Response | undefined {
  const match = path.match(/^\/api\/v1\/questions\/(\d+)\/similar-candidates(?:\/scan)?$/);
  if (!match) return undefined;
  return {
    ok: true, status: 200,
    json: async () => ({
      question_id: Number(match[1]), canonical_question_id: null, candidate_state: null,
      total_count: 0, unresolved_count: 0, confirmation_blocked: false,
      scan_required: false, candidates: [],
    }),
  } as Response;
}

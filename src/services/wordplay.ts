import { apiClient } from "./api-client";
import { Track } from "@/types";

export type WordplayStatus = "pending" | "approved";
export type WordplayEvidenceType =
  | "hypothesis"
  | "edit_listing"
  | "performance";
export type WordplayVerificationStatus = "unverified" | "tested";
export type WordplaySectionPosition = "unknown" | "start" | "middle" | "end";
export type WordplaySourceCueMode =
  | "section_end"
  | "cue_drumming"
  | "cue_drumming_intro";

export interface WordplayPair {
  id: number;
  from_track_id: number;
  to_track_id: number;
  keyword: string;
  source_phrase: string;
  target_phrase: string;
  from_timestamp: number | null;
  to_timestamp: number | null;
  /** Cue 打ちに使う声ネタの終端。旧レコードでは未設定。 */
  source_cue_end_timestamp?: number | null;
  /** 次曲のイントロを走らせ始める位置。旧レコードでは未設定。 */
  target_intro_timestamp?: number | null;
  /** 次曲の狙ったワードに着地する位置。旧レコードでは to_timestamp を使う。 */
  target_landing_timestamp?: number | null;
  /** 前曲の声ネタをどう使うか。 */
  source_cue_mode: WordplaySourceCueMode;
  source_cue_fit?: boolean;
  target_timing_fit?: boolean;
  source_section_position: WordplaySectionPosition;
  target_section_position: WordplaySectionPosition;
  transition_notes: string;
  source_url: string;
  evidence_type: WordplayEvidenceType;
  verification_status: WordplayVerificationStatus;
  status: WordplayStatus;
  bpm_delta_percent: number | null;
  boundary_fit: boolean;
  /** 2曲のスタイル／曲調がこのワードプレイに適合するか。旧レコードでは未設定。 */
  style_fit?: boolean;
  created_at: string;
  updated_at: string;
  from_track: Track | null;
  to_track: Track | null;
}

export interface WordplayPairList {
  items: WordplayPair[];
  total: number;
}

export interface ListWordplayPairsParams {
  status?: WordplayStatus;
  query?: string;
  from_track_id?: number;
  limit?: number;
  offset?: number;
}

export interface CreateWordplayPairInput {
  from_track_id: number;
  to_track_id: number;
  keyword: string;
  source_phrase: string;
  target_phrase: string;
  from_timestamp?: number | null;
  to_timestamp?: number | null;
  source_cue_end_timestamp?: number | null;
  target_intro_timestamp?: number | null;
  target_landing_timestamp?: number | null;
  source_cue_mode?: WordplaySourceCueMode;
  source_section_position?: WordplaySectionPosition;
  target_section_position?: WordplaySectionPosition;
  transition_notes?: string;
  source_url?: string;
  evidence_type?: WordplayEvidenceType;
  verification_status?: WordplayVerificationStatus;
}

export interface UpdateWordplayPairInput {
  from_track_id?: number;
  to_track_id?: number;
  keyword?: string;
  source_phrase?: string;
  target_phrase?: string;
  from_timestamp?: number | null;
  to_timestamp?: number | null;
  source_cue_end_timestamp?: number | null;
  target_intro_timestamp?: number | null;
  target_landing_timestamp?: number | null;
  source_cue_mode?: WordplaySourceCueMode;
  source_section_position?: WordplaySectionPosition;
  target_section_position?: WordplaySectionPosition;
  transition_notes?: string;
  source_url?: string;
  evidence_type?: WordplayEvidenceType;
  verification_status?: WordplayVerificationStatus;
}

export const wordplayService = {
  list: (params: ListWordplayPairsParams = {}) =>
    apiClient.get<WordplayPairList>("/wordplay-pairs", { ...params }),

  propose: (input: CreateWordplayPairInput) =>
    apiClient.post<WordplayPair>("/wordplay-pairs", input),

  approve: (id: number) =>
    apiClient.post<WordplayPair>(`/wordplay-pairs/${id}/approve`, {}),

  update: (id: number, input: UpdateWordplayPairInput) =>
    apiClient.patch<WordplayPair>(`/wordplay-pairs/${id}`, input),

  remove: (id: number) => apiClient.delete(`/wordplay-pairs/${id}`),
};

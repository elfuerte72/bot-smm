export interface MeResponse {
  id: number;
  username: string | null;
  first_name: string | null;
  is_owner: boolean;
}

export type PostStatus = "draft" | "publishing" | "published" | "rejected";

export interface Post {
  id: number;
  created_at: string | null;
  status: PostStatus | null;
  title: string;
  preview: string;
  primary_source_url: string | null;
  tg_message_id: number | null;
  published_at: string | null;
  total_reactions: number | null;
}

export interface PostsStats {
  draft: number;
  publishing: number;
  published: number;
  rejected: number;
  total: number;
}

export interface PostsListResponse {
  items: Post[];
  total: number;
  offset: number;
  limit: number;
}

export interface DraftEvent {
  id: number;
  event_type: "created" | "edited" | "regenerated_from" | "approved" | "rejected";
  actor_user_id: number | null;
  created_at: string | null;
  payload: Record<string, unknown>;
}

export interface ReactionEntry {
  emoji: string;
  count: number;
}

export interface ReactionsAgg {
  total_count: number;
  reactions: ReactionEntry[];
  updated_at: string | null;
}

export interface PostDetailResponse {
  post: Post & { formatted_text: string; tg_channel_url: string | null };
  events: DraftEvent[];
  reactions: ReactionsAgg | null;
}

export interface ChannelSnapshot {
  ts: string;
  member_count: number;
}

export interface ChannelStats {
  channel_id: string;
  title: string;
  member_count: number | null;
  snapshots: ChannelSnapshot[];
  days: number;
}

export interface ReactionRow {
  tg_message_id: number;
  channel_id: string;
  total_count: number;
  reactions: ReactionEntry[];
  updated_at: string | null;
  title: string;
  published_at: string | null;
  draft_id: number | null;
}

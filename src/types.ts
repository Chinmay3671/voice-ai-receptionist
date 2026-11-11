export type ReceptionistEvent =
  | { type: 'slots_checked'; date: string; count: number }
  | { type: 'booking_confirmed'; name: string; phone: string; start: string; link: string }
  | { type: 'booking_failed'; reason: string }
  | { type: 'interrupted' };

export interface ActivityItem {
  id: string;
  timestamp: string;
  event: ReceptionistEvent;
}

export type ConnectionStatus = 'Connecting' | 'Live' | 'Interrupted' | 'Disconnected';

export type AgentVoiceState = 'idle' | 'listening' | 'thinking' | 'speaking';


import React, { useState, useEffect, useRef, useCallback } from 'react';
import {
  LiveKitRoom,
  RoomAudioRenderer,
  useConnectionState,
  useVoiceAssistant,
  useLocalParticipant,
  useDataChannel,
} from '@livekit/components-react';
import { ConnectionState } from 'livekit-client';
import {
  Phone,
  PhoneOff,
  Mic,
  AlertCircle,
  Activity,
  CalendarDays,
  ShieldCheck,
  Building2,
  Clock,
} from 'lucide-react';
import { AudioVisualizer } from './components/AudioVisualizer';
import { ActivityLog } from './components/ActivityLog';
import { ReceptionistEvent, ActivityItem, ConnectionStatus, AgentVoiceState } from './types';

interface TokenResponse {
  token: string;
  url: string;
  room: string;
  identity: string;
}

/**
 * Inner room component that accesses LiveKit hooks
 */
const CallWorkspace: React.FC<{
  isStartingCall: boolean;
  onStartCall: () => void;
  onEndCall: () => void;
  callError: string | null;
  activities: ActivityItem[];
  onNewActivity: (event: ReceptionistEvent) => void;
}> = ({
  isStartingCall,
  onStartCall,
  onEndCall,
  callError,
  activities,
  onNewActivity,
}) => {
  const connectionState = useConnectionState();
  const { state: agentRawState, audioTrack: agentAudioTrack } = useVoiceAssistant();
  const { localParticipant, microphoneTrack } = useLocalParticipant();

  const [isInterrupted, setIsInterrupted] = useState<boolean>(false);
  const interruptTimeoutRef = useRef<number | null>(null);

  // Call duration counter
  const [durationSec, setDurationSec] = useState<number>(0);

  useEffect(() => {
    let timer: number | null = null;
    if (connectionState === ConnectionState.Connected) {
      timer = window.setInterval(() => {
        setDurationSec((prev) => prev + 1);
      }, 1000);
    } else {
      setDurationSec(0);
    }
    return () => {
      if (timer) clearInterval(timer);
    };
  }, [connectionState]);

  // Data channel for real-time receptionist events
  useDataChannel('receptionist', (msg) => {
    try {
      const decoded = new TextDecoder().decode(msg.payload);
      const parsed = JSON.parse(decoded) as ReceptionistEvent;
      onNewActivity(parsed);

      if (parsed.type === 'interrupted') {
        setIsInterrupted(true);
        if (interruptTimeoutRef.current) {
          window.clearTimeout(interruptTimeoutRef.current);
        }
        interruptTimeoutRef.current = window.setTimeout(() => {
          setIsInterrupted(false);
        }, 2000);
      }
    } catch (e) {
      console.error('Failed to parse receptionist data payload:', e);
    }
  });

  // Cleanup timeout on unmount
  useEffect(() => {
    return () => {
      if (interruptTimeoutRef.current) {
        window.clearTimeout(interruptTimeoutRef.current);
      }
    };
  }, []);

  // Compute status badge
  let status: ConnectionStatus = 'Disconnected';
  if (connectionState === ConnectionState.Connecting) {
    status = 'Connecting';
  } else if (connectionState === ConnectionState.Connected) {
    status = isInterrupted ? 'Interrupted' : 'Live';
  }

  const isCallActive = connectionState === ConnectionState.Connected;
  const agentState: AgentVoiceState = (agentRawState as AgentVoiceState) || 'idle';

  // Format call duration MM:SS
  const formatDuration = (totalSeconds: number): string => {
    const mins = Math.floor(totalSeconds / 60);
    const secs = totalSeconds % 60;
    return `${mins.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}`;
  };

  // Local microphone track reference
  const micTrackRef = microphoneTrack
    ? {
        participant: localParticipant,
        source: microphoneTrack.source,
        publication: microphoneTrack,
      }
    : undefined;

  return (
    <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 w-full max-w-7xl mx-auto">
      {/* Main Receptionist Calling Console (8 cols) */}
      <div className="lg:col-span-8 flex flex-col gap-6">
        {/* Main Card */}
        <div className="bg-white rounded-3xl border border-slate-200/90 shadow-sm p-6 sm:p-8 flex flex-col justify-between min-h-[520px]">
          {/* Header & Status */}
          <div className="flex flex-wrap items-center justify-between gap-4 pb-6 border-b border-slate-100">
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-2xl bg-teal-50 border border-teal-100 flex items-center justify-center text-teal-700 shadow-xs">
                <Building2 className="w-5 h-5" />
              </div>
              <div>
                <h1 className="font-['Bricolage_Grotesque',sans-serif] text-xl font-bold text-slate-900 tracking-tight">
                  Apex Wellness Clinic
                </h1>
                <p className="text-xs text-slate-500 flex items-center gap-1.5 mt-0.5">
                  <ShieldCheck className="w-3.5 h-3.5 text-teal-600 inline" />
                  <span>AI Front-Desk Voice Assistant &bull; Live Google Calendar</span>
                </p>
              </div>
            </div>

            {/* Dynamic Status Badges */}
            <div className="flex items-center gap-3">
              {isCallActive && (
                <div className="flex items-center gap-1.5 px-3 py-1 bg-slate-100 text-slate-700 rounded-full text-xs font-semibold font-mono">
                  <Clock className="w-3.5 h-3.5 text-slate-500" />
                  <span>{formatDuration(durationSec)}</span>
                </div>
              )}

              {/* Status Badge */}
              <div
                className={`flex items-center gap-2 px-3.5 py-1.5 rounded-full text-xs font-bold uppercase tracking-wider transition-colors ${
                  status === 'Live'
                    ? 'bg-emerald-50 text-emerald-700 border border-emerald-200/80'
                    : status === 'Interrupted'
                    ? 'bg-amber-50 text-amber-700 border border-amber-300'
                    : status === 'Connecting'
                    ? 'bg-sky-50 text-sky-700 border border-sky-200 animate-pulse'
                    : 'bg-slate-100 text-slate-500 border border-slate-200'
                }`}
              >
                <span
                  className={`w-2 h-2 rounded-full ${
                    status === 'Live'
                      ? 'bg-emerald-500 ring-2 ring-emerald-300 animate-pulse'
                      : status === 'Interrupted'
                      ? 'bg-amber-500 ring-2 ring-amber-300'
                      : status === 'Connecting'
                      ? 'bg-sky-500'
                      : 'bg-slate-400'
                  }`}
                />
                <span>{status}</span>
              </div>
            </div>
          </div>

          {/* Central Hero Waveform */}
          <div className="my-auto py-8 flex flex-col items-center justify-center">
            {isCallActive ? (
              <div className="w-full flex flex-col items-center">
                {/* Agent State Label */}
                <div className="mb-3 flex items-center gap-2">
                  <span
                    className={`inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-semibold uppercase tracking-wider ${
                      agentState === 'speaking'
                        ? 'bg-teal-100/70 text-teal-800 border border-teal-200'
                        : agentState === 'listening'
                        ? 'bg-slate-100 text-slate-700'
                        : agentState === 'thinking'
                        ? 'bg-amber-100 text-amber-800 border border-amber-200'
                        : 'bg-slate-100 text-slate-500'
                    }`}
                  >
                    <Activity className="w-3.5 h-3.5" />
                    Receptionist: {agentState}
                  </span>
                </div>

                {/* Hero Waveform */}
                <AudioVisualizer
                  trackRef={agentAudioTrack}
                  variant="hero"
                  bands={28}
                  agentState={agentState}
                />

                <p className="text-xs text-slate-400 mt-3 text-center">
                  Barge-in enabled &bull; Interrupt naturally at any time
                </p>
              </div>
            ) : (
              <div className="text-center py-10 max-w-md mx-auto">
                <div className="w-16 h-16 rounded-3xl bg-teal-50 border border-teal-100/80 flex items-center justify-center text-teal-700 mx-auto mb-4 shadow-sm">
                  <Phone className="w-7 h-7" />
                </div>
                <h2 className="font-['Bricolage_Grotesque',sans-serif] text-xl font-bold text-slate-900">
                  Ready to assist your appointment
                </h2>
                <p className="text-sm text-slate-500 mt-2 leading-relaxed">
                  Click &ldquo;Start call&rdquo; below to speak directly with our receptionist.
                  Ask about available slots or schedule a visit in real time.
                </p>
              </div>
            )}
          </div>

          {/* Error Message Display */}
          {callError && (
            <div className="mb-4 p-3.5 rounded-xl border border-rose-200 bg-rose-50 flex items-start gap-3 text-rose-800 text-sm">
              <AlertCircle className="w-5 h-5 text-rose-600 shrink-0 mt-0.5" />
              <div>
                <p className="font-semibold text-xs uppercase tracking-wide">Call Error</p>
                <p className="text-xs mt-0.5">{callError}</p>
              </div>
            </div>
          )}

          {/* Footer Controls & Caller Mic Monitor */}
          <div className="pt-6 border-t border-slate-100 flex flex-col sm:flex-row items-center justify-between gap-4">
            {/* Caller Mic Monitor (active during call) */}
            {isCallActive ? (
              <div className="flex items-center gap-3 w-full sm:w-auto bg-slate-50 border border-slate-200/70 px-3.5 py-2 rounded-2xl">
                <div className="w-6 h-6 rounded-full bg-slate-200/80 flex items-center justify-center text-slate-600">
                  <Mic className="w-3.5 h-3.5" />
                </div>
                <div className="flex flex-col">
                  <span className="text-[10px] font-semibold uppercase text-slate-500">Your Mic</span>
                  <div className="w-24">
                    <AudioVisualizer trackRef={micTrackRef} variant="compact" bands={10} />
                  </div>
                </div>
              </div>
            ) : (
              <div className="flex items-center gap-2 text-xs text-slate-500">
                <CalendarDays className="w-4 h-4 text-teal-700" />
                <span>Mon&ndash;Sat 9:00 AM &ndash; 5:00 PM</span>
              </div>
            )}

            {/* Start / End Call Button */}
            <div className="w-full sm:w-auto">
              {isCallActive ? (
                <button
                  type="button"
                  onClick={onEndCall}
                  className="w-full sm:w-auto inline-flex items-center justify-center gap-2 px-6 py-3.5 rounded-2xl bg-rose-600 hover:bg-rose-700 active:bg-rose-800 text-white font-semibold text-sm shadow-md shadow-rose-600/20 transition-all focus:outline-none focus:ring-4 focus:ring-rose-300 cursor-pointer"
                >
                  <PhoneOff className="w-4 h-4" />
                  <span>End call</span>
                </button>
              ) : (
                <button
                  type="button"
                  disabled={isStartingCall}
                  onClick={onStartCall}
                  className="w-full sm:w-auto inline-flex items-center justify-center gap-2.5 px-8 py-3.5 rounded-2xl bg-teal-700 hover:bg-teal-800 active:bg-teal-900 disabled:opacity-60 text-white font-semibold text-sm shadow-lg shadow-teal-700/20 transition-all focus:outline-none focus:ring-4 focus:ring-teal-300 cursor-pointer"
                >
                  {isStartingCall ? (
                    <>
                      <div className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                      <span>Connecting...</span>
                    </>
                  ) : (
                    <>
                      <Phone className="w-4 h-4" />
                      <span>Start call</span>
                    </>
                  )}
                </button>
              )}
            </div>
          </div>
        </div>
      </div>

      {/* Side Panel: Live Activity (4 cols) */}
      <div className="lg:col-span-4 h-full min-h-[520px]">
        <ActivityLog activities={activities} />
      </div>
    </div>
  );
};

export default function App() {
  const [connectionDetails, setConnectionDetails] = useState<TokenResponse | null>(null);
  const [isStartingCall, setIsStartingCall] = useState<boolean>(false);
  const [callError, setCallError] = useState<string | null>(null);
  const [activities, setActivities] = useState<ActivityItem[]>([]);

  const handleStartCall = async () => {
    setIsStartingCall(true);
    setCallError(null);

    try {
      // Prompt microphone permissions early to provide clear error handling
      try {
        const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        stream.getTracks().forEach((t) => t.stop());
      } catch (micErr: unknown) {
        const message = micErr instanceof Error ? micErr.message : 'Microphone permission denied';
        throw new Error(`Microphone access required: ${message}`);
      }

      // Fetch LiveKit room token from backend server
      const res = await fetch('/api/token', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
      });

      if (!res.ok) {
        const errJson = await res.json().catch(() => ({}));
        throw new Error(errJson.error || `Token server returned status ${res.status}`);
      }

      const data: TokenResponse = await res.json();
      setConnectionDetails(data);
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : 'Failed to connect to receptionist';
      setCallError(message);
      setConnectionDetails(null);
    } finally {
      setIsStartingCall(false);
    }
  };

  const handleEndCall = () => {
    setConnectionDetails(null);
  };

  const handleNewActivity = useCallback((event: ReceptionistEvent) => {
    const timestamp = new Date().toLocaleTimeString([], {
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
    });
    setActivities((prev) => [
      {
        id: `${Date.now()}-${Math.random().toString(36).slice(2, 7)}`,
        timestamp,
        event,
      },
      ...prev,
    ]);
  }, []);

  return (
    <div className="min-h-screen bg-[#f3f4f6] flex flex-col justify-between p-4 sm:p-6 md:p-8">
      {/* LiveKitRoom is always mounted as requested */}
      <LiveKitRoom
        serverUrl={connectionDetails?.url || ''}
        token={connectionDetails?.token || ''}
        connect={!!connectionDetails}
        audio={true}
        video={false}
        onError={(err) => {
          console.error('[LiveKitRoom] error:', err);
          setCallError(err.message || 'LiveKit connection error');
          setConnectionDetails(null);
        }}
      >
        <RoomAudioRenderer />
        <CallWorkspace
          isStartingCall={isStartingCall}
          onStartCall={handleStartCall}
          onEndCall={handleEndCall}
          callError={callError}
          activities={activities}
          onNewActivity={handleNewActivity}
        />
      </LiveKitRoom>

      {/* Subtle Footer */}
      <footer className="mt-8 text-center text-xs text-slate-400">
        Voice AI Receptionist &bull; Sub-1.2s conversational latency &bull; Deepgram Nova-3 + Groq Llama-3.3-70B + ElevenLabs
      </footer>
    </div>
  );
}


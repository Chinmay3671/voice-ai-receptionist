import React from 'react';
import { useMultibandTrackVolume, TrackReferenceOrPlaceholder } from '@livekit/components-react';

interface AudioVisualizerProps {
  trackRef?: TrackReferenceOrPlaceholder;
  bands?: number;
  variant?: 'hero' | 'compact';
  agentState?: 'idle' | 'listening' | 'thinking' | 'speaking';
  label?: string;
}

export const AudioVisualizer: React.FC<AudioVisualizerProps> = ({
  trackRef,
  bands = 24,
  variant = 'hero',
  agentState = 'idle',
  label,
}) => {
  // Compute multiband audio volume frequencies
  const rawVolumes = useMultibandTrackVolume(trackRef, {
    bands,
    loPass: 80,
    hiPass: 500,
  });

  const volumes = rawVolumes && rawVolumes.length === bands ? rawVolumes : new Array(bands).fill(0);
  const isHero = variant === 'hero';

  // Determine bar colors and container styling based on agent state
  const isSpeaking = agentState === 'speaking';
  const isThinking = agentState === 'thinking';
  const isListening = agentState === 'listening';

  return (
    <div className={`flex flex-col items-center justify-center w-full ${isHero ? 'py-4' : 'py-1'}`}>
      {label && (
        <div className="flex items-center gap-1.5 mb-2 text-xs font-semibold tracking-wider uppercase text-slate-500">
          <span>{label}</span>
          {isSpeaking && (
            <span className="w-2 h-2 rounded-full bg-teal-500 animate-ping" />
          )}
        </div>
      )}

      <div
        className={`flex items-end justify-center gap-1.5 w-full ${
          isHero ? 'h-28 max-w-xl' : 'h-8 max-w-xs'
        }`}
        role="img"
        aria-label={`${label || 'Audio'} visualizer, state: ${agentState}`}
      >
        {volumes.map((vol, index) => {
          // Normalize volume height
          let heightPercent = Math.max(8, Math.min(100, Math.round(vol * 130)));

          // Subtle wave when thinking
          if (isThinking) {
            const phase = (index / bands) * Math.PI * 2;
            heightPercent = Math.max(15, Math.round(25 + 15 * Math.sin(phase)));
          } else if (isListening && heightPercent <= 10) {
            // Subtle ambient pulse when listening
            heightPercent = 10;
          }

          let barColor = 'bg-slate-300';
          if (isHero) {
            if (isSpeaking) {
              barColor = 'bg-teal-600 shadow-sm shadow-teal-500/30';
            } else if (isThinking) {
              barColor = 'bg-amber-500/80 animate-pulse';
            } else if (isListening) {
              barColor = 'bg-teal-700/60';
            }
          } else {
            // Caller mic
            barColor = vol > 0.05 ? 'bg-emerald-600' : 'bg-slate-300';
          }

          return (
            <div
              key={index}
              className={`rounded-full transition-all duration-75 ${
                isHero ? 'w-2 sm:w-2.5' : 'w-1.5'
              } ${barColor}`}
              style={{
                height: `${heightPercent}%`,
                minHeight: isHero ? '8px' : '4px',
              }}
            />
          );
        })}
      </div>
    </div>
  );
};


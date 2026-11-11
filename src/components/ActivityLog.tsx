import React from 'react';
import { Calendar, CheckCircle2, XCircle, Zap, Clock, ExternalLink } from 'lucide-react';
import { ActivityItem } from '../types';

interface ActivityLogProps {
  activities: ActivityItem[];
}

export const ActivityLog: React.FC<ActivityLogProps> = ({ activities }) => {
  return (
    <div className="flex flex-col h-full bg-white rounded-2xl border border-slate-200/80 shadow-sm overflow-hidden">
      {/* Header */}
      <div className="px-5 py-4 border-b border-slate-100 flex items-center justify-between bg-slate-50/70">
        <div className="flex items-center gap-2">
          <div className="w-2.5 h-2.5 rounded-full bg-teal-600 animate-pulse" />
          <h2 className="font-['Bricolage_Grotesque',sans-serif] text-base font-semibold text-slate-800">
            Live Activity
          </h2>
        </div>
        <span className="text-xs font-medium text-slate-400 bg-slate-100 px-2.5 py-0.5 rounded-full">
          {activities.length} {activities.length === 1 ? 'event' : 'events'}
        </span>
      </div>

      {/* List / Empty State */}
      <div className="flex-1 p-4 overflow-y-auto space-y-3">
        {activities.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-56 text-center px-4">
            <div className="w-12 h-12 rounded-full bg-teal-50 flex items-center justify-center text-teal-600 mb-3">
              <Calendar className="w-6 h-6 stroke-[1.5]" />
            </div>
            <p className="text-sm font-medium text-slate-700">No events yet</p>
            <p className="text-xs text-slate-400 mt-1 max-w-[220px]">
              Actions taken by the receptionist (checking slot availability, confirmations, interruptions) will appear here in real time.
            </p>
          </div>
        ) : (
          activities.map((item) => {
            const { event, id, timestamp } = item;

            if (event.type === 'booking_confirmed') {
              return (
                <div
                  key={id}
                  className="p-3.5 rounded-xl border border-emerald-200 bg-emerald-50/70 transition-all text-slate-800"
                >
                  <div className="flex items-start justify-between gap-2">
                    <div className="flex items-center gap-1.5 text-emerald-800 font-semibold text-xs uppercase tracking-wide">
                      <CheckCircle2 className="w-4 h-4 text-emerald-600" />
                      Booking Confirmed
                    </div>
                    <span className="text-[11px] text-slate-400">{timestamp}</span>
                  </div>

                  <div className="mt-2.5 text-sm space-y-1">
                    <div className="font-semibold text-slate-900">{event.name}</div>
                    <div className="text-xs text-slate-600">Phone: {event.phone}</div>
                    <div className="text-xs text-slate-600 flex items-center gap-1">
                      <Clock className="w-3.5 h-3.5 text-slate-400 inline" />
                      <span>{new Date(event.start).toLocaleString([], { dateStyle: 'medium', timeStyle: 'short' })}</span>
                    </div>
                  </div>

                  {event.link && (
                    <a
                      href={event.link}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="inline-flex items-center gap-1 mt-2.5 text-xs font-semibold text-teal-700 hover:text-teal-900 underline underline-offset-2"
                    >
                      <span>View in Google Calendar</span>
                      <ExternalLink className="w-3 h-3" />
                    </a>
                  )}
                </div>
              );
            }

            if (event.type === 'booking_failed') {
              return (
                <div
                  key={id}
                  className="p-3.5 rounded-xl border border-rose-200 bg-rose-50/60 text-slate-800"
                >
                  <div className="flex items-start justify-between gap-2">
                    <div className="flex items-center gap-1.5 text-rose-800 font-semibold text-xs uppercase tracking-wide">
                      <XCircle className="w-4 h-4 text-rose-600" />
                      Booking Failed
                    </div>
                    <span className="text-[11px] text-slate-400">{timestamp}</span>
                  </div>
                  <p className="mt-1.5 text-xs text-rose-700">{event.reason}</p>
                </div>
              );
            }

            if (event.type === 'slots_checked') {
              return (
                <div
                  key={id}
                  className="p-3.5 rounded-xl border border-teal-100 bg-teal-50/50 text-slate-800"
                >
                  <div className="flex items-start justify-between gap-2">
                    <div className="flex items-center gap-1.5 text-teal-800 font-semibold text-xs uppercase tracking-wide">
                      <Calendar className="w-4 h-4 text-teal-600" />
                      Slots Checked
                    </div>
                    <span className="text-[11px] text-slate-400">{timestamp}</span>
                  </div>
                  <div className="mt-1.5 text-xs text-slate-600">
                    Date: <span className="font-medium text-slate-800">{event.date}</span> &bull; Found{' '}
                    <span className="font-semibold text-teal-700">{event.count}</span> available{' '}
                    {event.count === 1 ? 'slot' : 'slots'}
                  </div>
                </div>
              );
            }

            if (event.type === 'interrupted') {
              return (
                <div
                  key={id}
                  className="p-3 rounded-xl border border-amber-200 bg-amber-50/70 text-slate-800"
                >
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-1.5 text-amber-800 font-semibold text-xs uppercase tracking-wide">
                      <Zap className="w-3.5 h-3.5 text-amber-600" />
                      Interrupted
                    </div>
                    <span className="text-[11px] text-slate-400">{timestamp}</span>
                  </div>
                  <p className="text-[11px] text-amber-700 mt-1">
                    Caller barged in. Assistant stopped speaking immediately.
                  </p>
                </div>
              );
            }

            return null;
          })
        )}
      </div>
    </div>
  );
};


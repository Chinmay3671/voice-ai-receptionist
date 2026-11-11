import express, { Request, Response, NextFunction } from 'express';
import cors from 'cors';
import helmet from 'helmet';
import rateLimit from 'express-rate-limit';
import dotenv from 'dotenv';
import path from 'path';
import crypto from 'crypto';
import { AccessToken, WebhookReceiver } from 'livekit-server-sdk';

// Load environment variables from local directory and project root
dotenv.config({ path: path.resolve(process.cwd(), '.env') });
dotenv.config({ path: path.resolve(process.cwd(), '../.env') });

const LIVEKIT_URL = process.env.LIVEKIT_URL;
const LIVEKIT_API_KEY = process.env.LIVEKIT_API_KEY;
const LIVEKIT_API_SECRET = process.env.LIVEKIT_API_SECRET;
const PORT = parseInt(process.env.PORT || '3001', 10);
const CLIENT_ORIGIN = process.env.CLIENT_ORIGIN || 'http://localhost:5173';

// Fail fast at startup if required env vars are missing
if (!LIVEKIT_URL || !LIVEKIT_API_KEY || !LIVEKIT_API_SECRET) {
  const missing: string[] = [];
  if (!LIVEKIT_URL) missing.push('LIVEKIT_URL');
  if (!LIVEKIT_API_KEY) missing.push('LIVEKIT_API_KEY');
  if (!LIVEKIT_API_SECRET) missing.push('LIVEKIT_API_SECRET');
  console.error(`FATAL: Missing required environment variables: ${missing.join(', ')}`);
  process.exit(1);
}

const app = express();

// Security headers
app.use(helmet());

// CORS configuration
app.use(
  cors({
    origin: (origin, callback) => {
      // Allow requests with no origin (e.g. mobile apps, curl) or matching CLIENT_ORIGIN
      if (!origin || origin === CLIENT_ORIGIN) {
        callback(null, true);
      } else {
        callback(new Error(`CORS blocked for origin: ${origin}`));
      }
    },
    credentials: true,
    methods: ['GET', 'POST', 'OPTIONS'],
    allowedHeaders: ['Content-Type', 'Authorization'],
  })
);

// Webhook Receiver instance
const webhookReceiver = new WebhookReceiver(LIVEKIT_API_KEY, LIVEKIT_API_SECRET);

/**
 * LiveKit Webhook Endpoint
 * Must process the raw body BEFORE global express.json() is applied.
 */
app.post(
  '/api/livekit/webhook',
  express.raw({ type: '*/*' }),
  async (req: Request, res: Response): Promise<void> => {
    try {
      const authHeader = req.headers.authorization;
      if (!authHeader) {
        res.status(401).json({ error: 'Missing Authorization header' });
        return;
      }

      const rawBody = Buffer.isBuffer(req.body)
        ? req.body.toString('utf-8')
        : typeof req.body === 'string'
        ? req.body
        : JSON.stringify(req.body);

      const event = await webhookReceiver.receive(rawBody, authHeader);

      // Log webhook lifecycle events
      switch (event.event) {
        case 'room_started':
          console.log(`[LiveKit Webhook] Room started: ${event.room?.name || 'unknown'}`);
          break;
        case 'participant_joined':
          console.log(
            `[LiveKit Webhook] Participant joined: ${event.participant?.identity || 'unknown'} in room: ${event.room?.name || 'unknown'}`
          );
          break;
        case 'room_finished':
          console.log(`[LiveKit Webhook] Room finished: ${event.room?.name || 'unknown'}`);
          break;
        default:
          console.log(`[LiveKit Webhook] Received event: ${event.event}`);
      }

      res.status(200).send('OK');
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : 'Unknown webhook verification error';
      console.error(`[LiveKit Webhook] Verification failure: ${message}`);
      res.status(400).send(`Webhook error: ${message}`);
    }
  }
);

// JSON body parser for subsequent routes
app.use(express.json());

// Health check endpoint
app.get('/health', (_req: Request, res: Response) => {
  res.status(200).json({
    status: 'ok',
    timestamp: new Date().toISOString(),
    service: 'voice-ai-receptionist-server',
  });
});

// Rate limiting for token endpoint (10 requests per minute per IP)
const tokenRateLimiter = rateLimit({
  windowMs: 60 * 1000,
  max: 10,
  standardHeaders: true,
  legacyHeaders: false,
  message: { error: 'Too many token requests from this IP. Please try again after 1 minute.' },
});

interface TokenRequestBody {
  roomName?: string;
  participantName?: string;
}

/**
 * Sanitize string input: strip HTML, trim, allow only safe characters
 */
function sanitizeInput(str: unknown, maxLen = 64): string {
  if (typeof str !== 'string') return '';
  return str
    .replace(/[<>'"]/g, '')
    .trim()
    .slice(0, maxLen);
}

/**
 * POST /api/token
 * Generates a unique room and identity per call.
 * Issues an AccessToken with 10 min TTL and appropriate video/data grants.
 */
app.post(
  '/api/token',
  tokenRateLimiter,
  async (req: Request<unknown, unknown, TokenRequestBody>, res: Response): Promise<void> => {
    try {
      // Validate and sanitize any incoming body parameters
      const requestedRoom = sanitizeInput(req.body?.roomName);
      const requestedName = sanitizeInput(req.body?.participantName);

      // Unique room name and participant identity per call
      const uniqueSuffix = crypto.randomUUID();
      const room = requestedRoom ? `${requestedRoom}-${uniqueSuffix.slice(0, 8)}` : `receptionist-${uniqueSuffix}`;
      const identity = `caller-${uniqueSuffix.slice(0, 8)}`;
      const participantName = requestedName || `Guest-${identity.slice(-4)}`;

      // Create token with 10 minute TTL
      const token = new AccessToken(LIVEKIT_API_KEY, LIVEKIT_API_SECRET, {
        identity,
        name: participantName,
        ttl: '10m',
      });

      // Grant permissions for joining, publishing audio, subscribing, and data messages
      token.addGrant({
        roomJoin: true,
        room,
        canPublish: true,
        canSubscribe: true,
        canPublishData: true,
      });

      const jwt = await token.toJwt();

      res.status(200).json({
        token: jwt,
        url: LIVEKIT_URL,
        room,
        identity,
      });
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : 'Failed to issue room token';
      console.error('[Token Server] Error creating token:', message);
      res.status(500).json({ error: 'Internal server error generating room token' });
    }
  }
);

// Global error handler
app.use((err: Error, _req: Request, res: Response, _next: NextFunction) => {
  console.error('[Server Error]:', err.message);
  res.status(500).json({ error: 'Internal server error' });
});

// Start listening
app.listen(PORT, () => {
  console.log(`[Token Server] Running on http://localhost:${PORT}`);
  console.log(`[Token Server] Permitted CORS origin: ${CLIENT_ORIGIN}`);
});


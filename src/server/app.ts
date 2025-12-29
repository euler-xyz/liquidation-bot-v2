import Fastify, { type FastifyInstance } from 'fastify';
import cors from '@fastify/cors';
import swagger from '@fastify/swagger';
import swaggerUi from '@fastify/swagger-ui';
import { logger } from '../utils/logger';
import { healthRoutes } from './routes/health';
import { positionsRoutes } from './routes/positions';

export async function createApp(): Promise<FastifyInstance> {
  const app = Fastify({
    logger: false, // We use our own pino logger
    trustProxy: true,
  });

  // Register CORS
  await app.register(cors, {
    origin: true,
    methods: ['GET', 'POST', 'OPTIONS'],
  });

  // Register Swagger
  await app.register(swagger, {
    openapi: {
      info: {
        title: 'Liquidation Bot API',
        description: 'Multi-chain liquidation bot for Euler protocol',
        version: '1.0.0',
      },
      servers: [
        {
          url: 'http://localhost:8080',
          description: 'Local development server',
        },
      ],
      tags: [
        { name: 'health', description: 'Health check endpoints' },
        { name: 'liquidation', description: 'Liquidation monitoring endpoints' },
      ],
    },
  });

  // Register Swagger UI
  await app.register(swaggerUi, {
    routePrefix: '/docs',
    uiConfig: {
      docExpansion: 'list',
      deepLinking: true,
    },
    staticCSP: true,
  });

  // Register routes
  await app.register(healthRoutes, { prefix: '/' });
  await app.register(positionsRoutes, { prefix: '/liquidation' });

  // Error handler
  app.setErrorHandler((error, request, reply) => {
    logger.error(
      {
        error: error.message,
        stack: error.stack,
        url: request.url,
        method: request.method,
      },
      'Request error'
    );

    reply.status(error.statusCode ?? 500).send({
      error: error.message,
      statusCode: error.statusCode ?? 500,
    });
  });

  // Request logging
  app.addHook('onRequest', async (request) => {
    logger.debug(
      {
        method: request.method,
        url: request.url,
        ip: request.ip,
      },
      'Incoming request'
    );
  });

  app.addHook('onResponse', async (request, reply) => {
    logger.debug(
      {
        method: request.method,
        url: request.url,
        statusCode: reply.statusCode,
        responseTime: reply.elapsedTime,
      },
      'Request completed'
    );
  });

  return app;
}

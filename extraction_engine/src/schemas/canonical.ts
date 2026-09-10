import { CanonicalJsonSchema } from '../types/index.js';

export const StartupCanonicalSchema: CanonicalJsonSchema = {
  $schema: 'http://json-schema.org/draft-07/schema#',
  title: 'StartupRecord',
  type: 'object',
  required: ['schemaVersion', 'recordType', 'source', 'content', 'collectedAt'],
  additionalProperties: true,
  properties: {
    schemaVersion: { type: 'string', enum: ['1.0'] },
    recordType: { type: 'string', enum: ['STARTUP'] },
    source: {
      type: 'object',
      required: ['name', 'url'],
      properties: {
        name: { type: 'string', minLength: 1 },
        url: { type: 'string', minLength: 1 },
      },
    },
    content: {
      type: 'object',
      required: ['entityName'],
      properties: {
        entityName: { type: 'string', minLength: 1 },
        data: {
          type: 'object',
          properties: {
            employeeCount: {
              anyOf: [
                { type: 'integer', minimum: 0 },
                { type: 'null' },
              ],
            },
          },
        },
      },
    },
    collectedAt: { type: 'string' },
  },
};

export const ProductCanonicalSchema: CanonicalJsonSchema = {
  $schema: 'http://json-schema.org/draft-07/schema#',
  title: 'ProductRecord',
  type: 'object',
  required: ['schemaVersion', 'recordType', 'source', 'content', 'collectedAt'],
  additionalProperties: true,
  properties: {
    schemaVersion: { type: 'string', enum: ['1.0'] },
    recordType: { type: 'string', enum: ['PRODUCT'] },
    source: {
      type: 'object',
      required: ['name', 'url'],
      properties: {
        name: { type: 'string', minLength: 1 },
        url: { type: 'string', minLength: 1 },
      },
    },
    content: {
      type: 'object',
      required: ['startupName', 'pricingModel'],
      properties: {
        startupName: { type: 'string', minLength: 1 },
        pricingModel: {
          type: 'string',
          enum: ['FREE', 'FREEMIUM', 'PAID', 'ENTERPRISE'],
        },
      },
    },
    collectedAt: { type: 'string' },
  },
};

export const ResearchPaperCanonicalSchema: CanonicalJsonSchema = {
  $schema: 'http://json-schema.org/draft-07/schema#',
  title: 'ResearchPaperRecord',
  type: 'object',
  required: ['schemaVersion', 'recordType', 'source', 'content', 'collectedAt'],
  additionalProperties: true,
  properties: {
    schemaVersion: { type: 'string', enum: ['1.0'] },
    recordType: { type: 'string', enum: ['RESEARCH_PAPER'] },
    source: {
      type: 'object',
      required: ['name', 'url'],
      properties: {
        name: { type: 'string', minLength: 1 },
        url: { type: 'string', minLength: 1 },
      },
    },
    content: {
      type: 'object',
      required: ['title', 'authors', 'paper_url', 'github_stars', 'published_date'],
      properties: {
        title: { type: 'string', minLength: 1 },
        authors: {
          type: 'array',
          items: { type: 'string' },
        },
        paper_url: { type: 'string', minLength: 1 },
        github_url: {
          anyOf: [
            { type: 'string' },
            { type: 'null' },
          ],
        },
        github_stars: { type: 'integer', minimum: 0 },
        published_date: { type: 'string' },
      },
    },
    collectedAt: { type: 'string' },
  },
};

export const CanonicalSchemas = {
  STARTUP: StartupCanonicalSchema,
  PRODUCT: ProductCanonicalSchema,
  RESEARCH_PAPER: ResearchPaperCanonicalSchema,
};

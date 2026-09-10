import AjvModule from 'ajv';
import addFormatsModule from 'ajv-formats';
import { CanonicalJsonSchema } from '../types/index.js';
import { SchemaValidationError } from '../utils/errors.js';

// Handle ESM / CJS default import differences gracefully
const Ajv = (AjvModule as unknown as { default?: typeof AjvModule }).default || AjvModule;
const addFormats =
  (addFormatsModule as unknown as { default?: typeof addFormatsModule }).default ||
  addFormatsModule;

const ajv = new Ajv({
  allErrors: true,
  strict: false, // accommodate flexible properties in canonical schemas
  coerceTypes: false,
});
addFormats(ajv);

export interface ValidationResult<T = unknown> {
  valid: boolean;
  errors: unknown[];
  data?: T;
  formattedError?: string;
}

export function validateSchema<T = unknown>(
  schema: CanonicalJsonSchema,
  data: unknown
): ValidationResult<T> {
  const validate = ajv.compile(schema);
  const valid = validate(data);

  if (valid) {
    return {
      valid: true,
      errors: [],
      data: data as T,
    };
  }

  const errors = validate.errors || [];
  const formattedError = errors
    .map((err) => `${err.instancePath || '/'} ${err.message || 'is invalid'}`)
    .join('; ');

  return {
    valid: false,
    errors,
    formattedError,
  };
}

export function assertValidSchema<T = unknown>(
  schema: CanonicalJsonSchema,
  data: unknown,
  provider?: string,
  model?: string
): T {
  const result = validateSchema<T>(schema, data);
  if (!result.valid) {
    throw new SchemaValidationError({
      message: `Schema validation failed: ${result.formattedError}`,
      validationErrors: result.errors,
      invalidData: data,
      provider,
      model,
    });
  }
  return result.data!;
}

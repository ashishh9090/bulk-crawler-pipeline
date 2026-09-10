import AjvModule, { type ErrorObject } from 'ajv';
import addFormatsModule from 'ajv-formats';
import { CanonicalJsonSchema } from '../types/index.js';
import { SchemaValidationError } from '../utils/errors.js';

// Handle ESM / CJS interop cleanly across build targets
// eslint-disable-next-line @typescript-eslint/no-explicit-any
const AjvClass: any = (AjvModule as any).default || AjvModule;
// eslint-disable-next-line @typescript-eslint/no-explicit-any
const addFormatsFunc: any = (addFormatsModule as any).default || addFormatsModule;

const ajv = new AjvClass({
  allErrors: true,
  strict: false,
  coerceTypes: false,
});
addFormatsFunc(ajv);

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

  const errors: ErrorObject[] = (validate.errors as ErrorObject[]) || [];
  const formattedError = errors
    .map((err: ErrorObject) => `${err.instancePath || '/'} ${err.message || 'is invalid'}`)
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

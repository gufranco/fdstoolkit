import { z } from 'zod';

export const FIELD_KINDS = ['file', 'files', 'text', 'number', 'flag', 'choice', 'auto'] as const;
export const JOB_STATES = ['running', 'waiting', 'done', 'failed'] as const;

export const FormFieldSchema = z.object({
  name: z.string().min(1),
  kind: z.enum(FIELD_KINDS),
  required: z.boolean(),
  accepts: z.string(),
  default: z.unknown(),
  options: z.array(z.string()),
  minimum: z.number().nullable(),
  maximum: z.number().nullable(),
  step: z.number().nullable(),
  min_length: z.number().int().nullable(),
  max_length: z.number().int().nullable(),
  hidden: z.boolean(),
});

export const CommandFormSchema = z.object({
  command: z.string().min(1),
  route: z.string().min(1),
  method: z.enum(['GET', 'POST']),
  family: z.string().min(1),
  summary: z.string(),
  needs_hardware: z.boolean(),
  fields: z.array(FormFieldSchema),
});

export const CatalogueSchema = z.object({
  forms: z.array(CommandFormSchema),
  families: z.array(z.string()),
});

export const DownloadSchema = z.object({
  name: z.string(),
  data: z.string(),
  size: z.number(),
  notes: z.array(z.string()).optional(),
});

export const JobSchema = z.object({
  id: z.string().min(1),
  command: z.string().min(1),
  writes: z.boolean(),
  stoppable: z.boolean(),
  stopping: z.boolean(),
  state: z.enum(JOB_STATES),
  steps: z.array(z.string()),
  prompt: z.string(),
  result: z.unknown(),
  error: z.string(),
  kept: z.unknown(),
});

export const CurrentJobSchema = z.object({ job: JobSchema.nullish() });

export const HardwareSchema = z.object({ connected: z.boolean(), detail: z.string() });

export const AnyAnswerSchema = z.unknown();

export type FormField = z.infer<typeof FormFieldSchema>;
export type CommandForm = z.infer<typeof CommandFormSchema>;
export type Catalogue = z.infer<typeof CatalogueSchema>;
export type Download = z.infer<typeof DownloadSchema>;
export type Job = z.infer<typeof JobSchema>;
export type JobState = Job['state'];
export type Hardware = z.infer<typeof HardwareSchema>;

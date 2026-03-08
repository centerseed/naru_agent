export interface GuardrailResult {
  passed: boolean;
  modifiedText: string | null;
  reason: string | null;
}

export interface BaseGuardrail {
  checkInput(message: string): Promise<GuardrailResult>;
  checkOutput(response: string): Promise<GuardrailResult>;
}

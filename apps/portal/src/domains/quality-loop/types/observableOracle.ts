export interface ObservableOracle { preconditions: string; action: string; observation: string; expected_result: string }
export const oracleKeys = ['preconditions', 'action', 'observation', 'expected_result'] as const

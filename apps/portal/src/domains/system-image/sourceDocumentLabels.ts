export const documentFieldLabels: Record<string, string> = {
  description: 'Description', acceptance_criterion: 'Acceptance criterion', precondition: 'Precondition',
  step: 'Step', expected_result: 'Expected result', reference: 'Reference', business_rule: 'Business rule',
}
export const documentGapLabels: Record<string, string> = {
  missing_acceptance_criterion: 'Missing acceptance criterion', missing_step: 'Missing test steps',
  missing_expected_result: 'Missing expected result', duplicate_external_id: 'Duplicate source identifier',
  no_explicit_record_identity: 'No explicit record identifier',
  script_not_executed: 'Script has not been executed', unreviewed_script_oracle: 'Script oracle has not been reviewed',
  no_explicit_component_identity: 'No explicit criterion or rule identifier',
  parent_identity_not_unique: 'Parent requirement identity is not unique',
  duplicate_component_id: 'Duplicate criterion or rule identifier within requirement',
  compound_source_field_not_decomposed: 'Compound source field retained without semantic splitting',
}

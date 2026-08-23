import { useAuthUser } from '../../domains/platform/useAuthSession'
import { useIdentityAdministration } from '../../domains/platform/identity/useIdentityAdministration'
import type { StudioSettingsControls } from '../../domains/platform/useStudioSettings'
import { useAvatarEditorModel, useUserAvatarImage } from '../../domains/platform/useUserAvatar'
import { AvatarEditor } from '../../shared/ui/AvatarEditor'
import { SettingsPopover } from './settings/SettingsPopover'
import { IdentityAdministrationPanel } from './settings/IdentityAdministrationPanel'
import { ProjectMembersPanel } from './settings/ProjectMembersPanel'

export function StudioSettingsLayer({
  open,
  settings,
  projectId,
  projectName,
}: {
  open: boolean
  settings: StudioSettingsControls
  projectId?: string
  projectName?: string
}) {
  const { data: user } = useAuthUser()
  const avatarImageUrl = useUserAvatarImage(user)
  const avatarEditor = useAvatarEditorModel({ variant: 'settings' })
  const identityAdministration = useIdentityAdministration(user)

  if (!open) return null

  return (
    <SettingsPopover
      settings={settings.settings}
      disabled={settings.settingsDisabled}
      statusMessage={settings.statusMessage}
      testing={settings.testingConnection}
      accountAdministration={(
        <IdentityAdministrationPanel
          user={user}
          avatarEditor={(
            <AvatarEditor
              user={user}
              avatarImageUrl={avatarImageUrl}
              variant="settings"
              pickerOpen={avatarEditor.pickerOpen}
              saving={avatarEditor.saving}
              status={avatarEditor.status}
              onPickerOpenChange={avatarEditor.setPickerOpen}
              onUploadAvatar={avatarEditor.uploadAvatar}
              onSelectPreset={avatarEditor.selectPreset}
            />
          )}
          administration={identityAdministration}
        />
      )}
      projectMembersPanel={projectId ? <ProjectMembersPanel projectId={projectId} projectName={projectName} /> : null}
      onTheme={settings.saveTheme}
      onLanguage={settings.saveLanguage}
      onNotification={settings.saveNotification}
      onSaveModel={settings.saveModel}
      onUpdateModel={settings.updateModel}
      onTestModel={settings.testModel}
      onActivateModel={settings.activateModel}
      onUseSystemDefaultModel={settings.useSystemDefaultModel}
    />
  )
}

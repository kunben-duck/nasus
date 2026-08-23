import { useNavigate } from 'react-router-dom'

import { useAuthUser } from '../../domains/platform/useAuthSession'
import { useAvatarEditorModel, usePlatformAccountSessionActions, useUserAvatarImage } from '../../domains/platform/useUserAvatar'
import { AvatarEditor } from '../../shared/ui/AvatarEditor'
import { UserAccountMenu } from '../../shared/ui/UserAccountMenu'

export function UserAccountMenuContainer() {
  const navigate = useNavigate()
  const { data: user } = useAuthUser()
  const avatarImageUrl = useUserAvatarImage(user)
  const avatarEditor = useAvatarEditorModel({ variant: 'account' })
  const accountActions = usePlatformAccountSessionActions()

  async function signOut() {
    await accountActions.signOut()
    navigate('/login', { replace: true })
  }

  function switchAccount() {
    accountActions.switchAccount()
    navigate('/login', { replace: true, state: { switchAccount: true } })
  }

  return (
    <UserAccountMenu
      user={user}
      avatarImageUrl={avatarImageUrl}
      avatarEditor={(
        <AvatarEditor
          user={user}
          avatarImageUrl={avatarImageUrl}
          variant="account"
          pickerOpen={avatarEditor.pickerOpen}
          saving={avatarEditor.saving}
          status={avatarEditor.status}
          onPickerOpenChange={avatarEditor.setPickerOpen}
          onUploadAvatar={avatarEditor.uploadAvatar}
          onSelectPreset={avatarEditor.selectPreset}
        />
      )}
      onSignOut={signOut}
      onSwitchAccount={switchAccount}
    />
  )
}

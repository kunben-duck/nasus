const java = Object.freeze({ roles: ['pg', 'redis'], executable: 'java',
  arguments: ['-jar', '/app/target.jar'], artifact: '/app/target.jar' })
const python = Object.freeze({ roles: ['pg'], executable: 'python',
  arguments: ['/app/target.pyz', 'runserver', '0.0.0.0:8080', '--noreload'], artifact: '/app/target.pyz' })

export function ownedEnvironmentProfile(inventory) {
  if (inventory === null || inventory.schema === 'nasus.owned-target-environment.v1' && !Object.hasOwn(inventory, 'profile')) return java
  if (inventory.schema === 'nasus.owned-target-environment.v2' && inventory.profile === 'nasus.python312-django-pg.v1') return python
  throw new Error('Owned target transport could not be verified.')
}

package com.autotest.platform.service;

import com.autotest.platform.dto.RolePermissionProfileDTO;
import com.autotest.platform.dto.UserDTO;
import com.autotest.platform.dto.UserTenantContextDTO;
import com.autotest.platform.entity.Tenant;
import com.autotest.platform.entity.TenantMembership;
import com.autotest.platform.entity.User;
import com.autotest.platform.repository.TenantMembershipRepository;
import com.autotest.platform.repository.TenantRepository;
import com.autotest.platform.repository.UserRepository;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.cache.annotation.Cacheable;
import org.springframework.data.domain.Page;
import org.springframework.data.domain.Pageable;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.util.StringUtils;

import java.util.Arrays;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Locale;
import java.util.Set;
import java.util.stream.Collectors;

@Service
@RequiredArgsConstructor
@Slf4j
public class UserService {

    private static final int MAX_AVATAR_LENGTH = 60000;

    private final UserRepository userRepository;
    private final TenantRepository tenantRepository;
    private final TenantMembershipRepository tenantMembershipRepository;
    private final TenantContextService tenantContextService;
    private final PasswordEncoder passwordEncoder;

    @Cacheable(value = "users", key = "#id")
    @Transactional(readOnly = true)
    public UserDTO getUserById(Long id) {
        User user = userRepository.findById(id)
                .orElseThrow(() -> new RuntimeException("User not found: " + id));
        return mapToDTO(user);
    }

    @Cacheable(value = "users", key = "#username")
    @Transactional(readOnly = true)
    public UserDTO getUserByUsername(String username) {
        User user = userRepository.findByUsername(username)
                .orElseThrow(() -> new RuntimeException("User not found: " + username));
        return mapToDTO(user);
    }

    @Transactional(readOnly = true)
    public Page<UserDTO> getAllUsers(Pageable pageable) {
        return userRepository.findAll(pageable).map(this::mapToDTO);
    }

    @Transactional(readOnly = true)
    public Page<UserDTO> searchUsers(String keyword, Pageable pageable) {
        return userRepository.searchUsers(keyword, pageable).map(this::mapToDTO);
    }

    @Transactional(readOnly = true)
    public List<RolePermissionProfileDTO> getRolePermissionProfiles() {
        return List.of(
                buildRoleProfile(User.UserRole.SYSTEM_ADMIN),
                buildRoleProfile(User.UserRole.OPS_ADMIN),
                buildRoleProfile(User.UserRole.OPERATIONS_ADMIN)
        );
    }

    @Transactional(readOnly = true)
    public UserTenantContextDTO getUserTenantContext(String username) {
        TenantContextService.CurrentTenant current = tenantContextService.resolveCurrentTenant(username);
        List<UserTenantContextDTO.AvailableTenantItem> available = current.memberships().stream()
                .filter(item -> item.getTenant() != null && item.getTenant().getStatus() == Tenant.TenantStatus.ACTIVE)
                .map(item -> {
                    TenantMembership.ProjectRole role = item.getRole() == null
                            ? TenantMembership.ProjectRole.QA
                            : item.getRole().canonical();
                    return UserTenantContextDTO.AvailableTenantItem.builder()
                            .tenantId(item.getTenant().getId())
                            .tenantCode(item.getTenant().getTenantCode())
                            .tenantName(item.getTenant().getTenantName())
                            .role(role)
                            .roleDisplayName(role.displayName())
                            .build();
                })
                .toList();

        return UserTenantContextDTO.builder()
                .currentTenantId(current.tenant().getId())
                .currentTenantCode(current.tenant().getTenantCode())
                .currentTenantName(current.tenant().getTenantName())
                .availableTenants(available)
                .build();
    }

    @Transactional
    public UserTenantContextDTO switchUserTenant(String username, Long tenantId) {
        tenantContextService.switchActiveTenant(username, tenantId);
        return getUserTenantContext(username);
    }

    @Transactional
    public UserDTO createUser(UserDTO userDTO, String password) {
        if (userRepository.existsByUsername(userDTO.getUsername())) {
            throw new RuntimeException("Username already exists");
        }
        if (userRepository.existsByEmail(userDTO.getEmail())) {
            throw new RuntimeException("Email already exists");
        }

        User.UserRole role = normalizeRole(userDTO.getRole());
        List<String> permissions = resolvePermissions(role, userDTO.getPermissions());

        User user = User.builder()
                .username(userDTO.getUsername())
                .email(userDTO.getEmail())
                .password(passwordEncoder.encode(password))
                .fullName(userDTO.getFullName())
                .role(role)
                .permissions(joinPermissions(permissions))
                .status(User.UserStatus.ACTIVE)
                .avatar(sanitizeAvatar(userDTO.getAvatar()))
                .build();

        User savedUser = userRepository.save(user);
        bootstrapTenantForSystemAdmin(savedUser);
        log.info("Created user: {}", savedUser.getUsername());
        return mapToDTO(savedUser);
    }

    @Transactional
    public UserDTO updateUser(Long id, UserDTO userDTO) {
        User user = userRepository.findById(id)
                .orElseThrow(() -> new RuntimeException("User not found: " + id));

        boolean roleChanged = false;
        if (userDTO.getFullName() != null) {
            user.setFullName(userDTO.getFullName().trim());
        }
        if (userDTO.getAvatar() != null) {
            user.setAvatar(sanitizeAvatar(userDTO.getAvatar()));
        }
        if (userDTO.getRole() != null) {
            user.setRole(normalizeRole(userDTO.getRole()));
            roleChanged = true;
        }
        if (userDTO.getStatus() != null) {
            user.setStatus(userDTO.getStatus());
        }
        if (userDTO.getPermissions() != null) {
            user.setPermissions(joinPermissions(resolvePermissions(user.getRole(), userDTO.getPermissions())));
        } else if (roleChanged) {
            user.setPermissions(joinPermissions(User.defaultPermissionsByRole(user.getRole())));
        }

        User updatedUser = userRepository.save(user);
        log.info("Updated user: {}", updatedUser.getUsername());
        return mapToDTO(updatedUser);
    }

    @Transactional
    public UserDTO updateCurrentUserProfile(String username, String fullName, String avatar) {
        User user = userRepository.findByUsername(username)
                .orElseThrow(() -> new RuntimeException("User not found: " + username));

        String normalizedName = fullName == null ? "" : fullName.trim();
        if (normalizedName.isEmpty()) {
            throw new RuntimeException("Full name cannot be empty");
        }
        user.setFullName(normalizedName);
        user.setAvatar(sanitizeAvatar(avatar));

        User updatedUser = userRepository.save(user);
        log.info("Updated profile for user: {}", updatedUser.getUsername());
        return mapToDTO(updatedUser);
    }

    @Transactional
    public void deleteUser(Long id) {
        User user = userRepository.findById(id)
                .orElseThrow(() -> new RuntimeException("User not found: " + id));
        user.setStatus(User.UserStatus.INACTIVE);
        userRepository.save(user);
        log.info("Deactivated user: {}", user.getUsername());
    }

    @Transactional
    public void changePassword(Long id, String oldPassword, String newPassword) {
        User user = userRepository.findById(id)
                .orElseThrow(() -> new RuntimeException("User not found: " + id));

        if (!passwordEncoder.matches(oldPassword, user.getPassword())) {
            throw new RuntimeException("Invalid old password");
        }

        user.setPassword(passwordEncoder.encode(newPassword));
        userRepository.save(user);
        log.info("Changed password for user: {}", user.getUsername());
    }

    @Transactional(readOnly = true)
    public long countActiveUsers() {
        return userRepository.countByStatus(User.UserStatus.ACTIVE);
    }

    private User.UserRole normalizeRole(User.UserRole role) {
        if (role == null) return User.UserRole.OPERATIONS_ADMIN;
        return role.canonical();
    }

    private List<String> resolvePermissions(User.UserRole role, List<String> permissions) {
        if (permissions == null || permissions.isEmpty()) {
            return User.defaultPermissionsByRole(normalizeRole(role));
        }
        Set<String> normalized = permissions.stream()
                .filter(item -> item != null && !item.trim().isEmpty())
                .map(String::trim)
                .collect(Collectors.toCollection(LinkedHashSet::new));
        return normalized.stream().toList();
    }

    private String joinPermissions(List<String> permissions) {
        if (permissions == null || permissions.isEmpty()) return null;
        return String.join(",", permissions);
    }

    private String sanitizeAvatar(String avatar) {
        if (avatar == null) return null;
        String normalized = avatar.trim();
        if (normalized.isEmpty()) return null;
        if (normalized.length() > MAX_AVATAR_LENGTH) {
            throw new RuntimeException("Avatar payload too large");
        }
        return normalized;
    }

    private List<String> parsePermissions(String permissions, User.UserRole role) {
        if (permissions == null || permissions.trim().isEmpty()) {
            return User.defaultPermissionsByRole(normalizeRole(role));
        }
        Set<String> normalized = Arrays.stream(permissions.split(","))
                .map(String::trim)
                .filter(item -> !item.isEmpty())
                .collect(Collectors.toCollection(LinkedHashSet::new));
        return normalized.stream().toList();
    }

    private RolePermissionProfileDTO buildRoleProfile(User.UserRole role) {
        User.UserRole canonicalRole = normalizeRole(role);
        return RolePermissionProfileDTO.builder()
                .role(canonicalRole)
                .roleDisplayName(canonicalRole.displayName())
                .defaultPermissions(User.defaultPermissionsByRole(canonicalRole))
                .build();
    }

    private UserDTO mapToDTO(User user) {
        User.UserRole canonicalRole = normalizeRole(user.getRole());
        Tenant activeTenant = resolveActiveTenant(user);
        return UserDTO.builder()
                .id(user.getId())
                .username(user.getUsername())
                .email(user.getEmail())
                .fullName(user.getFullName())
                .role(canonicalRole)
                .roleDisplayName(canonicalRole.displayName())
                .status(user.getStatus())
                .permissions(parsePermissions(user.getPermissions(), canonicalRole))
                .avatar(user.getAvatar())
                .activeTenantId(activeTenant != null ? activeTenant.getId() : user.getActiveTenantId())
                .activeTenantCode(activeTenant != null ? activeTenant.getTenantCode() : null)
                .activeTenantName(activeTenant != null ? activeTenant.getTenantName() : null)
                .createdAt(user.getCreatedAt())
                .lastLoginAt(user.getLastLoginAt())
                .build();
    }

    private Tenant resolveActiveTenant(User user) {
        Long activeTenantId = user.getActiveTenantId();
        if (activeTenantId != null) {
            return tenantRepository.findById(activeTenantId).orElse(null);
        }
        List<TenantMembership> memberships = tenantMembershipRepository.findByUserIdAndStatus(
                user.getId(),
                TenantMembership.MembershipStatus.ACTIVE
        );
        return memberships.stream()
                .map(TenantMembership::getTenant)
                .filter(tenant -> tenant != null && tenant.getStatus() == Tenant.TenantStatus.ACTIVE)
                .findFirst()
                .orElse(null);
    }

    private void bootstrapTenantForSystemAdmin(User user) {
        User.UserRole role = normalizeRole(user.getRole());
        if (!role.isSystemAdmin()) {
            return;
        }

        List<TenantMembership> existingMemberships = tenantMembershipRepository.findByUserIdAndStatus(
                user.getId(),
                TenantMembership.MembershipStatus.ACTIVE
        );
        if (!existingMemberships.isEmpty()) {
            if (user.getActiveTenantId() == null) {
                Long fallbackTenantId = existingMemberships.stream()
                        .map(TenantMembership::getTenant)
                        .filter(tenant -> tenant != null && tenant.getStatus() == Tenant.TenantStatus.ACTIVE)
                        .map(Tenant::getId)
                        .findFirst()
                        .orElse(null);
                if (fallbackTenantId != null) {
                    user.setActiveTenantId(fallbackTenantId);
                    userRepository.save(user);
                }
            }
            return;
        }

        String normalizedUsername = user.getUsername() == null ? "ADMIN" : user.getUsername()
                .toUpperCase(Locale.ROOT)
                .replaceAll("[^A-Z0-9_-]", "_")
                .replaceAll("_+", "_");
        if (!StringUtils.hasText(normalizedUsername)) {
            normalizedUsername = "ADMIN";
        }
        if (normalizedUsername.length() > 16) {
            normalizedUsername = normalizedUsername.substring(0, 16);
        }

        String baseCode = "TEN_" + normalizedUsername;
        if (baseCode.length() > 32) {
            baseCode = baseCode.substring(0, 32);
        }
        String tenantCode = baseCode;
        int counter = 1;
        while (tenantRepository.existsByTenantCode(tenantCode)) {
            String suffix = "_" + counter++;
            int maxLen = 32 - suffix.length();
            String prefix = maxLen > 0 ? baseCode.substring(0, Math.min(baseCode.length(), maxLen)) : "";
            tenantCode = prefix + suffix;
        }

        String tenantName;
        if (StringUtils.hasText(user.getFullName())) {
            tenantName = user.getFullName().trim() + " Workspace";
        } else {
            tenantName = user.getUsername() + " Workspace";
        }
        if (tenantName.length() > 100) {
            tenantName = tenantName.substring(0, 100);
        }

        Tenant tenant = tenantRepository.save(Tenant.builder()
                .tenantCode(tenantCode)
                .tenantName(tenantName)
                .ownerAdmin(user)
                .status(Tenant.TenantStatus.ACTIVE)
                .build());

        tenantMembershipRepository.save(TenantMembership.builder()
                .tenant(tenant)
                .user(user)
                .role(TenantMembership.ProjectRole.TEST_MANAGER)
                .status(TenantMembership.MembershipStatus.ACTIVE)
                .build());

        user.setActiveTenantId(tenant.getId());
        userRepository.save(user);
        log.info("Bootstrapped tenant {} for system admin {}", tenantCode, user.getUsername());
    }
}

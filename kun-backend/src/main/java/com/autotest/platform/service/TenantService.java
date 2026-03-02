package com.autotest.platform.service;

import com.autotest.platform.dto.TenantDTO;
import com.autotest.platform.dto.TenantMembershipDTO;
import com.autotest.platform.dto.TenantRoleProfileDTO;
import com.autotest.platform.dto.UserDTO;
import com.autotest.platform.entity.Tenant;
import com.autotest.platform.entity.TenantMembership;
import com.autotest.platform.entity.User;
import com.autotest.platform.repository.TenantMembershipRepository;
import com.autotest.platform.repository.TenantRepository;
import com.autotest.platform.repository.UserRepository;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.util.StringUtils;

import java.util.Comparator;
import java.util.List;
import java.util.Locale;
import java.util.Objects;
import java.util.regex.Pattern;

@Service
@RequiredArgsConstructor
@Slf4j
public class TenantService {

    private static final Pattern TENANT_CODE_PATTERN = Pattern.compile("^[A-Z0-9][A-Z0-9_-]{1,31}$");

    private final TenantRepository tenantRepository;
    private final TenantMembershipRepository tenantMembershipRepository;
    private final UserRepository userRepository;

    @Transactional(readOnly = true)
    public List<TenantDTO> listOwnedTenants(String adminUsername) {
        User admin = getAdminUser(adminUsername);
        List<Tenant> tenants = tenantRepository.findByOwnerAdminIdOrderByCreatedAtDesc(admin.getId());
        return tenants.stream()
                .map(this::mapTenant)
                .toList();
    }

    @Transactional(readOnly = true)
    public List<TenantRoleProfileDTO> getAssignableProjectRoleProfiles() {
        return List.of(
                buildProjectRoleProfile(TenantMembership.ProjectRole.TEST_MANAGER),
                buildProjectRoleProfile(TenantMembership.ProjectRole.TEST_ENGINEER),
                buildProjectRoleProfile(TenantMembership.ProjectRole.QA)
        );
    }

    @Transactional
    public TenantDTO createTenant(String adminUsername, String tenantCode, String tenantName) {
        User admin = getAdminUser(adminUsername);
        String normalizedName = normalizeTenantName(tenantName);
        String normalizedCode = normalizeTenantCode(tenantCode, normalizedName);

        if (tenantRepository.existsByTenantCode(normalizedCode)) {
            throw new RuntimeException("Tenant code already exists: " + normalizedCode);
        }

        Tenant tenant = Tenant.builder()
                .tenantCode(normalizedCode)
                .tenantName(normalizedName)
                .ownerAdmin(admin)
                .status(Tenant.TenantStatus.ACTIVE)
                .build();
        Tenant saved = tenantRepository.save(tenant);

        TenantMembership ownerMembership = TenantMembership.builder()
                .tenant(saved)
                .user(admin)
                .role(TenantMembership.ProjectRole.TEST_MANAGER)
                .status(TenantMembership.MembershipStatus.ACTIVE)
                .build();
        tenantMembershipRepository.save(ownerMembership);

        if (admin.getActiveTenantId() == null) {
            admin.setActiveTenantId(saved.getId());
            userRepository.save(admin);
        }

        log.info("Created tenant: {} ({}) by {}", saved.getTenantName(), saved.getTenantCode(), adminUsername);
        return mapTenant(saved);
    }

    @Transactional(readOnly = true)
    public List<TenantMembershipDTO> listTenantMembers(String adminUsername, Long tenantId) {
        Tenant tenant = requireOwnedTenant(adminUsername, tenantId);
        return tenantMembershipRepository.findByTenantIdAndStatus(tenant.getId(), TenantMembership.MembershipStatus.ACTIVE)
                .stream()
                .map(this::mapMembership)
                .toList();
    }

    @Transactional
    public TenantMembershipDTO upsertTenantMember(String adminUsername,
                                                  Long tenantId,
                                                  Long userId,
                                                  TenantMembership.ProjectRole role) {
        Tenant tenant = requireOwnedTenant(adminUsername, tenantId);
        User user = userRepository.findById(userId)
                .orElseThrow(() -> new RuntimeException("User not found: " + userId));

        TenantMembership.ProjectRole resolvedRole = normalizeTenantMemberRole(role);

        TenantMembership membership = tenantMembershipRepository.findByTenantIdAndUserId(tenantId, userId)
                .map(existing -> {
                    existing.setRole(resolvedRole);
                    existing.setStatus(TenantMembership.MembershipStatus.ACTIVE);
                    return existing;
                })
                .orElseGet(() -> TenantMembership.builder()
                        .tenant(tenant)
                        .user(user)
                        .role(resolvedRole)
                        .status(TenantMembership.MembershipStatus.ACTIVE)
                        .build());

        TenantMembership saved = tenantMembershipRepository.save(membership);

        if (user.getActiveTenantId() == null) {
            user.setActiveTenantId(tenantId);
            userRepository.save(user);
        }

        log.info("Updated tenant membership: tenantId={}, userId={}, role={}", tenantId, userId, resolvedRole);
        return mapMembership(saved);
    }

    @Transactional
    public void removeTenantMember(String adminUsername, Long tenantId, Long userId) {
        Tenant tenant = requireOwnedTenant(adminUsername, tenantId);
        if (tenant.getOwnerAdmin() != null && Objects.equals(tenant.getOwnerAdmin().getId(), userId)) {
            throw new RuntimeException("Tenant owner cannot be removed");
        }

        TenantMembership membership = tenantMembershipRepository.findByTenantIdAndUserId(tenantId, userId)
                .orElseThrow(() -> new RuntimeException("Tenant member not found"));

        membership.setStatus(TenantMembership.MembershipStatus.INACTIVE);
        tenantMembershipRepository.save(membership);

        userRepository.findById(userId).ifPresent(user -> {
            if (!Objects.equals(user.getActiveTenantId(), tenantId)) {
                return;
            }
            List<TenantMembership> activeMemberships = tenantMembershipRepository.findByUserIdAndStatus(
                    userId,
                    TenantMembership.MembershipStatus.ACTIVE
            );
            Long fallbackTenantId = activeMemberships.stream()
                    .filter(item -> item.getTenant() != null && item.getTenant().getStatus() == Tenant.TenantStatus.ACTIVE)
                    .map(item -> item.getTenant().getId())
                    .sorted(Comparator.naturalOrder())
                    .findFirst()
                    .orElse(null);
            user.setActiveTenantId(fallbackTenantId);
            userRepository.save(user);
        });

        log.info("Removed tenant member: tenantId={}, userId={}", tenantId, userId);
    }

    @Transactional(readOnly = true)
    public List<UserDTO> listAssignableUsers(String adminUsername) {
        getAdminUser(adminUsername);
        return userRepository.findAll().stream()
                .filter(user -> user.getStatus() == User.UserStatus.ACTIVE)
                .map(this::mapUser)
                .sorted(Comparator.comparing(UserDTO::getUsername, String.CASE_INSENSITIVE_ORDER))
                .toList();
    }

    @Transactional(readOnly = true)
    public Tenant requireOwnedTenant(String adminUsername, Long tenantId) {
        User admin = getAdminUser(adminUsername);
        return tenantRepository.findByIdAndOwnerAdminId(tenantId, admin.getId())
                .orElseThrow(() -> new RuntimeException("Tenant not found or no permission"));
    }

    private User getAdminUser(String username) {
        User user = userRepository.findByUsername(username)
                .orElseThrow(() -> new RuntimeException("User not found: " + username));
        User.UserRole role = user.getRole() == null ? User.UserRole.OPERATIONS_ADMIN : user.getRole().canonical();
        if (!role.isSystemAdmin()) {
            throw new RuntimeException("Only system administrator can manage tenants");
        }
        return user;
    }

    private String normalizeTenantName(String tenantName) {
        String normalized = StringUtils.hasText(tenantName) ? tenantName.trim() : "";
        if (normalized.isEmpty()) {
            throw new RuntimeException("Tenant name is required");
        }
        if (normalized.length() > 100) {
            throw new RuntimeException("Tenant name too long");
        }
        return normalized;
    }

    private String normalizeTenantCode(String tenantCode, String tenantName) {
        String source = StringUtils.hasText(tenantCode) ? tenantCode.trim() : tenantName;
        String normalized = source
                .toUpperCase(Locale.ROOT)
                .replaceAll("[^A-Z0-9_-]", "_")
                .replaceAll("_+", "_");

        if (normalized.length() > 32) {
            normalized = normalized.substring(0, 32);
        }

        if (!TENANT_CODE_PATTERN.matcher(normalized).matches()) {
            throw new RuntimeException("Invalid tenant code. Use letters, numbers, _ or -, length 2-32");
        }
        return normalized;
    }

    private TenantDTO mapTenant(Tenant tenant) {
        int memberCount = tenantMembershipRepository.findByTenantIdAndStatus(
                tenant.getId(),
                TenantMembership.MembershipStatus.ACTIVE
        ).size();

        return TenantDTO.builder()
                .id(tenant.getId())
                .tenantCode(tenant.getTenantCode())
                .tenantName(tenant.getTenantName())
                .status(tenant.getStatus())
                .ownerAdminId(tenant.getOwnerAdmin() != null ? tenant.getOwnerAdmin().getId() : null)
                .ownerAdminUsername(tenant.getOwnerAdmin() != null ? tenant.getOwnerAdmin().getUsername() : null)
                .memberCount(memberCount)
                .createdAt(tenant.getCreatedAt())
                .updatedAt(tenant.getUpdatedAt())
                .build();
    }

    private TenantMembershipDTO mapMembership(TenantMembership membership) {
        User user = membership.getUser();
        TenantMembership.ProjectRole canonical = membership.getRole() == null
                ? TenantMembership.ProjectRole.QA
                : membership.getRole().canonical();
        return TenantMembershipDTO.builder()
                .id(membership.getId())
                .tenantId(membership.getTenant() != null ? membership.getTenant().getId() : null)
                .userId(user != null ? user.getId() : null)
                .username(user != null ? user.getUsername() : null)
                .fullName(user != null ? user.getFullName() : null)
                .email(user != null ? user.getEmail() : null)
                .role(canonical)
                .roleDisplayName(canonical.displayName())
                .status(membership.getStatus())
                .createdAt(membership.getCreatedAt())
                .updatedAt(membership.getUpdatedAt())
                .build();
    }

    private UserDTO mapUser(User user) {
        User.UserRole role = user.getRole() == null ? User.UserRole.OPERATIONS_ADMIN : user.getRole().canonical();
        return UserDTO.builder()
                .id(user.getId())
                .username(user.getUsername())
                .email(user.getEmail())
                .fullName(user.getFullName())
                .role(role)
                .roleDisplayName(role.displayName())
                .status(user.getStatus())
                .avatar(user.getAvatar())
                .createdAt(user.getCreatedAt())
                .lastLoginAt(user.getLastLoginAt())
                .activeTenantId(user.getActiveTenantId())
                .build();
    }

    private TenantRoleProfileDTO buildProjectRoleProfile(TenantMembership.ProjectRole role) {
        TenantMembership.ProjectRole canonicalRole = role.canonical();
        return TenantRoleProfileDTO.builder()
                .role(canonicalRole)
                .roleDisplayName(canonicalRole.displayName())
                .build();
    }

    private TenantMembership.ProjectRole normalizeTenantMemberRole(TenantMembership.ProjectRole role) {
        if (role == null) {
            return TenantMembership.ProjectRole.QA;
        }
        TenantMembership.ProjectRole canonical = role.canonical();
        if (role != canonical || !canonical.isAssignable()) {
            throw new RuntimeException("Tenant role only supports TEST_MANAGER, TEST_ENGINEER or QA");
        }
        return canonical;
    }
}

package com.autotest.platform.service;

import com.autotest.platform.entity.Tenant;
import com.autotest.platform.entity.TenantMembership;
import com.autotest.platform.entity.User;
import com.autotest.platform.repository.TenantMembershipRepository;
import com.autotest.platform.repository.TenantRepository;
import com.autotest.platform.repository.UserRepository;
import lombok.RequiredArgsConstructor;
import org.springframework.security.core.Authentication;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.List;
import java.util.Optional;

@Service
@RequiredArgsConstructor
public class TenantContextService {

    private final UserRepository userRepository;
    private final TenantRepository tenantRepository;
    private final TenantMembershipRepository tenantMembershipRepository;

    @Transactional(readOnly = true)
    public CurrentTenant resolveCurrentTenant() {
        return resolveCurrentTenant(resolveAuthenticatedUsername());
    }

    @Transactional(readOnly = true)
    public CurrentTenant resolveCurrentTenant(String username) {
        User user = userRepository.findByUsername(username)
                .orElseThrow(() -> new RuntimeException("User not found: " + username));

        List<TenantMembership> memberships = tenantMembershipRepository.findByUserIdAndStatus(
                user.getId(),
                TenantMembership.MembershipStatus.ACTIVE
        );
        if (memberships.isEmpty()) {
            throw new RuntimeException("Current user has no available tenant membership");
        }

        Long activeTenantId = user.getActiveTenantId();
        TenantMembership activeMembership = memberships.stream()
                .filter(item -> item.getTenant() != null && item.getTenant().getId().equals(activeTenantId))
                .findFirst()
                .orElse(memberships.get(0));

        Tenant tenant = activeMembership.getTenant();
        if (tenant == null) {
            throw new RuntimeException("Current tenant is invalid");
        }
        if (tenant.getStatus() != Tenant.TenantStatus.ACTIVE) {
            throw new RuntimeException("Current tenant is disabled: " + tenant.getTenantName());
        }

        return new CurrentTenant(user, tenant, activeMembership, memberships);
    }

    @Transactional(readOnly = true)
    public Long requireCurrentTenantId() {
        return resolveCurrentTenant().tenant().getId();
    }

    @Transactional(readOnly = true)
    public Optional<Long> tryResolveCurrentTenantId() {
        try {
            return Optional.of(requireCurrentTenantId());
        } catch (Exception ignored) {
            return Optional.empty();
        }
    }

    @Transactional(readOnly = true)
    public List<TenantMembership> getActiveMemberships(String username) {
        User user = userRepository.findByUsername(username)
                .orElseThrow(() -> new RuntimeException("User not found: " + username));
        return tenantMembershipRepository.findByUserIdAndStatus(user.getId(), TenantMembership.MembershipStatus.ACTIVE);
    }

    @Transactional
    public CurrentTenant switchActiveTenant(String username, Long tenantId) {
        if (tenantId == null) {
            throw new RuntimeException("tenantId is required");
        }

        User user = userRepository.findByUsername(username)
                .orElseThrow(() -> new RuntimeException("User not found: " + username));

        TenantMembership membership = tenantMembershipRepository
                .findByUserIdAndTenantIdAndStatus(user.getId(), tenantId, TenantMembership.MembershipStatus.ACTIVE)
                .orElseThrow(() -> new RuntimeException("Selected tenant is not available for current user"));

        Tenant tenant = membership.getTenant();
        if (tenant == null || tenant.getStatus() != Tenant.TenantStatus.ACTIVE) {
            throw new RuntimeException("Selected tenant is disabled");
        }

        user.setActiveTenantId(tenantId);
        userRepository.save(user);

        List<TenantMembership> memberships = tenantMembershipRepository.findByUserIdAndStatus(
                user.getId(),
                TenantMembership.MembershipStatus.ACTIVE
        );
        return new CurrentTenant(user, tenant, membership, memberships);
    }

    @Transactional(readOnly = true)
    public void assertUserHasTenantAccess(Long userId, Long tenantId) {
        if (userId == null || tenantId == null) {
            throw new RuntimeException("Tenant access check failed: missing user or tenant");
        }

        boolean exists = tenantMembershipRepository.existsByTenantIdAndUserIdAndStatus(
                tenantId,
                userId,
                TenantMembership.MembershipStatus.ACTIVE
        );
        if (!exists) {
            throw new RuntimeException("Tenant access denied");
        }
    }

    private String resolveAuthenticatedUsername() {
        Authentication authentication = SecurityContextHolder.getContext().getAuthentication();
        if (authentication == null || !authentication.isAuthenticated() || authentication.getName() == null) {
            throw new RuntimeException("Authentication required");
        }
        String username = authentication.getName();
        if ("anonymousUser".equalsIgnoreCase(username)) {
            throw new RuntimeException("Authentication required");
        }
        return username;
    }

    public record CurrentTenant(
            User user,
            Tenant tenant,
            TenantMembership activeMembership,
            List<TenantMembership> memberships
    ) {
    }
}

package com.autotest.platform.controller;

import com.autotest.platform.dto.ApiResponse;
import com.autotest.platform.dto.TenantDTO;
import com.autotest.platform.dto.TenantMembershipDTO;
import com.autotest.platform.dto.TenantRoleProfileDTO;
import com.autotest.platform.dto.UserDTO;
import com.autotest.platform.entity.TenantMembership;
import com.autotest.platform.service.TenantService;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;
import lombok.RequiredArgsConstructor;
import org.springframework.http.ResponseEntity;
import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.security.core.Authentication;
import org.springframework.web.bind.annotation.*;

import java.util.List;

@RestController
@RequestMapping("/tenants")
@RequiredArgsConstructor
@CrossOrigin(origins = "*")
public class TenantController {

    private final TenantService tenantService;

    @GetMapping
    @PreAuthorize("hasAnyRole('SYSTEM_ADMIN','ADMIN')")
    public ResponseEntity<ApiResponse<List<TenantDTO>>> listOwnedTenants(Authentication authentication) {
        List<TenantDTO> payload = tenantService.listOwnedTenants(authentication.getName());
        return ResponseEntity.ok(ApiResponse.success(payload));
    }

    @GetMapping("/roles")
    @PreAuthorize("hasAnyRole('SYSTEM_ADMIN','ADMIN')")
    public ResponseEntity<ApiResponse<List<TenantRoleProfileDTO>>> listTenantRoles() {
        return ResponseEntity.ok(ApiResponse.success(tenantService.getAssignableProjectRoleProfiles()));
    }

    @PostMapping
    @PreAuthorize("hasAnyRole('SYSTEM_ADMIN','ADMIN')")
    public ResponseEntity<ApiResponse<TenantDTO>> createTenant(@RequestBody CreateTenantRequest request,
                                                                Authentication authentication) {
        TenantDTO created = tenantService.createTenant(
                authentication.getName(),
                request.getTenantCode(),
                request.getTenantName()
        );
        return ResponseEntity.ok(ApiResponse.success("Tenant created", created));
    }

    @GetMapping("/users")
    @PreAuthorize("hasAnyRole('SYSTEM_ADMIN','ADMIN')")
    public ResponseEntity<ApiResponse<List<UserDTO>>> listAssignableUsers(Authentication authentication) {
        List<UserDTO> users = tenantService.listAssignableUsers(authentication.getName());
        return ResponseEntity.ok(ApiResponse.success(users));
    }

    @GetMapping("/{tenantId}/members")
    @PreAuthorize("hasAnyRole('SYSTEM_ADMIN','ADMIN')")
    public ResponseEntity<ApiResponse<List<TenantMembershipDTO>>> listMembers(@PathVariable Long tenantId,
                                                                               Authentication authentication) {
        List<TenantMembershipDTO> members = tenantService.listTenantMembers(authentication.getName(), tenantId);
        return ResponseEntity.ok(ApiResponse.success(members));
    }

    @PutMapping("/{tenantId}/members/{userId}")
    @PreAuthorize("hasAnyRole('SYSTEM_ADMIN','ADMIN')")
    public ResponseEntity<ApiResponse<TenantMembershipDTO>> upsertMember(@PathVariable Long tenantId,
                                                                          @PathVariable Long userId,
                                                                          @RequestBody UpsertTenantMemberRequest request,
                                                                          Authentication authentication) {
        TenantMembershipDTO updated = tenantService.upsertTenantMember(
                authentication.getName(),
                tenantId,
                userId,
                request.getRole()
        );
        return ResponseEntity.ok(ApiResponse.success("Tenant member updated", updated));
    }

    @DeleteMapping("/{tenantId}/members/{userId}")
    @PreAuthorize("hasAnyRole('SYSTEM_ADMIN','ADMIN')")
    public ResponseEntity<ApiResponse<Void>> removeMember(@PathVariable Long tenantId,
                                                           @PathVariable Long userId,
                                                           Authentication authentication) {
        tenantService.removeTenantMember(authentication.getName(), tenantId, userId);
        return ResponseEntity.ok(ApiResponse.success("Tenant member removed", null));
    }

    @Data
    @Builder
    @NoArgsConstructor
    @AllArgsConstructor
    public static class CreateTenantRequest {
        private String tenantCode;
        private String tenantName;
    }

    @Data
    @Builder
    @NoArgsConstructor
    @AllArgsConstructor
    public static class UpsertTenantMemberRequest {
        private TenantMembership.ProjectRole role;
    }
}

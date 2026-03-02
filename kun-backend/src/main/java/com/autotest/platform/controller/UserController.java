package com.autotest.platform.controller;

import com.autotest.platform.dto.ApiResponse;
import com.autotest.platform.dto.PageResponse;
import com.autotest.platform.dto.RolePermissionProfileDTO;
import com.autotest.platform.dto.UserDTO;
import com.autotest.platform.dto.UserTenantContextDTO;
import com.autotest.platform.service.UserService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.data.domain.PageRequest;
import org.springframework.data.domain.Pageable;
import org.springframework.data.domain.Sort;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.security.core.Authentication;
import org.springframework.web.bind.annotation.*;

import java.util.List;

@RestController
@RequestMapping("/users")
@RequiredArgsConstructor
@Slf4j
@CrossOrigin(origins = "*")
public class UserController {
    
    private final UserService userService;
    
    @GetMapping
    @PreAuthorize("hasAnyRole('SYSTEM_ADMIN','ADMIN')")
    public ResponseEntity<ApiResponse<PageResponse<UserDTO>>> getAllUsers(
            @RequestParam(defaultValue = "0") int page,
            @RequestParam(defaultValue = "20") int size,
            @RequestParam(defaultValue = "id,desc") String[] sort) {
        
        Pageable pageable = PageRequest.of(page, size, Sort.by(sort[0]).descending());
        PageResponse<UserDTO> users = PageResponse.from(userService.getAllUsers(pageable));
        return ResponseEntity.ok(ApiResponse.success(users));
    }

    @GetMapping("/roles")
    @PreAuthorize("hasAnyRole('SYSTEM_ADMIN','ADMIN')")
    public ResponseEntity<ApiResponse<List<RolePermissionProfileDTO>>> getRoleProfiles() {
        return ResponseEntity.ok(ApiResponse.success(userService.getRolePermissionProfiles()));
    }

    @PostMapping
    @PreAuthorize("hasAnyRole('SYSTEM_ADMIN','ADMIN')")
    public ResponseEntity<ApiResponse<UserDTO>> createUser(@RequestBody CreateUserRequest request) {
        UserDTO payload = UserDTO.builder()
                .username(request.getUsername())
                .email(request.getEmail())
                .fullName(request.getFullName())
                .role(request.getRole())
                .permissions(request.getPermissions())
                .build();
        UserDTO created = userService.createUser(payload, request.getPassword());
        return ResponseEntity.ok(ApiResponse.success("User created", created));
    }
    
    @GetMapping("/{id}")
    @PreAuthorize("hasAnyRole('SYSTEM_ADMIN','ADMIN')")
    public ResponseEntity<ApiResponse<UserDTO>> getUserById(@PathVariable Long id) {
        UserDTO user = userService.getUserById(id);
        return ResponseEntity.ok(ApiResponse.success(user));
    }
    
    @GetMapping("/search")
    @PreAuthorize("hasAnyRole('SYSTEM_ADMIN','ADMIN')")
    public ResponseEntity<ApiResponse<PageResponse<UserDTO>>> searchUsers(
            @RequestParam String keyword,
            @RequestParam(defaultValue = "0") int page,
            @RequestParam(defaultValue = "20") int size) {
        
        Pageable pageable = PageRequest.of(page, size);
        PageResponse<UserDTO> users = PageResponse.from(userService.searchUsers(keyword, pageable));
        return ResponseEntity.ok(ApiResponse.success(users));
    }
    
    @PutMapping("/{id}")
    @PreAuthorize("hasAnyRole('SYSTEM_ADMIN','ADMIN')")
    public ResponseEntity<ApiResponse<UserDTO>> updateUser(
            @PathVariable Long id,
            @RequestBody UserDTO userDTO) {
        UserDTO updatedUser = userService.updateUser(id, userDTO);
        return ResponseEntity.ok(ApiResponse.success("User updated", updatedUser));
    }
    
    @DeleteMapping("/{id}")
    @PreAuthorize("hasAnyRole('SYSTEM_ADMIN','ADMIN')")
    public ResponseEntity<ApiResponse<Void>> deleteUser(@PathVariable Long id) {
        userService.deleteUser(id);
        return ResponseEntity.ok(ApiResponse.success("User deleted", null));
    }
    
    @PostMapping("/{id}/change-password")
    public ResponseEntity<ApiResponse<Void>> changePassword(
            @PathVariable Long id,
            @RequestBody ChangePasswordRequest request,
            Authentication authentication) {
        UserDTO targetUser = userService.getUserById(id);
        boolean admin = isSystemAdmin(authentication);
        boolean self = authentication != null && authentication.getName().equals(targetUser.getUsername());
        if (!admin && !self) {
            return ResponseEntity.status(HttpStatus.FORBIDDEN)
                    .body(ApiResponse.error(403, "No permission to change this user's password"));
        }
        userService.changePassword(id, request.getOldPassword(), request.getNewPassword());
        return ResponseEntity.ok(ApiResponse.success("Password changed", null));
    }

    @PutMapping("/me/profile")
    public ResponseEntity<ApiResponse<UserDTO>> updateMyProfile(
            @RequestBody UpdateProfileRequest request,
            Authentication authentication) {
        if (authentication == null || authentication.getName() == null) {
            return ResponseEntity.status(HttpStatus.UNAUTHORIZED)
                    .body(ApiResponse.error(401, "Authentication required"));
        }
        UserDTO updated = userService.updateCurrentUserProfile(
                authentication.getName(),
                request.getFullName(),
                request.getAvatar()
        );
        return ResponseEntity.ok(ApiResponse.success("Profile updated", updated));
    }

    @GetMapping("/me/tenant-context")
    public ResponseEntity<ApiResponse<UserTenantContextDTO>> getMyTenantContext(Authentication authentication) {
        if (authentication == null || authentication.getName() == null) {
            return ResponseEntity.status(HttpStatus.UNAUTHORIZED)
                    .body(ApiResponse.error(401, "Authentication required"));
        }
        UserTenantContextDTO context = userService.getUserTenantContext(authentication.getName());
        return ResponseEntity.ok(ApiResponse.success(context));
    }

    @PutMapping("/me/tenant-context")
    public ResponseEntity<ApiResponse<UserTenantContextDTO>> switchMyTenant(
            @RequestBody SwitchTenantRequest request,
            Authentication authentication) {
        if (authentication == null || authentication.getName() == null) {
            return ResponseEntity.status(HttpStatus.UNAUTHORIZED)
                    .body(ApiResponse.error(401, "Authentication required"));
        }
        UserTenantContextDTO context = userService.switchUserTenant(authentication.getName(), request.getTenantId());
        return ResponseEntity.ok(ApiResponse.success("Tenant switched", context));
    }

    private boolean isSystemAdmin(Authentication authentication) {
        if (authentication == null) return false;
        return authentication.getAuthorities().stream().anyMatch(authority ->
                "ROLE_SYSTEM_ADMIN".equals(authority.getAuthority()) ||
                "ROLE_ADMIN".equals(authority.getAuthority()));
    }
    
    @lombok.Data
    @lombok.Builder
    @lombok.NoArgsConstructor
    @lombok.AllArgsConstructor
    public static class ChangePasswordRequest {
        private String oldPassword;
        private String newPassword;
    }

    @lombok.Data
    @lombok.Builder
    @lombok.NoArgsConstructor
    @lombok.AllArgsConstructor
    public static class UpdateProfileRequest {
        private String fullName;
        private String avatar;
    }

    @lombok.Data
    @lombok.Builder
    @lombok.NoArgsConstructor
    @lombok.AllArgsConstructor
    public static class CreateUserRequest {
        private String username;
        private String email;
        private String fullName;
        private String password;
        private com.autotest.platform.entity.User.UserRole role;
        private List<String> permissions;
    }

    @lombok.Data
    @lombok.Builder
    @lombok.NoArgsConstructor
    @lombok.AllArgsConstructor
    public static class SwitchTenantRequest {
        private Long tenantId;
    }
}

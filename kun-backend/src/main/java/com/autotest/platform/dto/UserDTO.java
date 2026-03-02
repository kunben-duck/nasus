package com.autotest.platform.dto;

import com.autotest.platform.entity.User;
import com.fasterxml.jackson.annotation.JsonInclude;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.time.LocalDateTime;
import java.util.List;

@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
@JsonInclude(JsonInclude.Include.NON_NULL)
public class UserDTO {
    
    private Long id;
    private String username;
    private String email;
    private String fullName;
    private User.UserRole role;
    private String roleDisplayName;
    private User.UserStatus status;
    private List<String> permissions;
    private String avatar;
    private Long activeTenantId;
    private String activeTenantCode;
    private String activeTenantName;
    private LocalDateTime createdAt;
    private LocalDateTime lastLoginAt;
}

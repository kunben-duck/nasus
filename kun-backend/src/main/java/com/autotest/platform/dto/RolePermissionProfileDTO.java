package com.autotest.platform.dto;

import com.autotest.platform.entity.User;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.util.List;

@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
public class RolePermissionProfileDTO {
    private User.UserRole role;
    private String roleDisplayName;
    private List<String> defaultPermissions;
}


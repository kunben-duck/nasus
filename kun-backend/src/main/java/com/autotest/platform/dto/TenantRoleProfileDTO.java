package com.autotest.platform.dto;

import com.autotest.platform.entity.TenantMembership;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
public class TenantRoleProfileDTO {
    private TenantMembership.ProjectRole role;
    private String roleDisplayName;
}

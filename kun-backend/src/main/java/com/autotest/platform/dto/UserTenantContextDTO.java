package com.autotest.platform.dto;

import com.autotest.platform.entity.TenantMembership;
import com.fasterxml.jackson.annotation.JsonInclude;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.util.List;

@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
@JsonInclude(JsonInclude.Include.NON_NULL)
public class UserTenantContextDTO {

    private Long currentTenantId;
    private String currentTenantCode;
    private String currentTenantName;
    private List<AvailableTenantItem> availableTenants;

    @Data
    @Builder
    @NoArgsConstructor
    @AllArgsConstructor
    public static class AvailableTenantItem {
        private Long tenantId;
        private String tenantCode;
        private String tenantName;
        private TenantMembership.ProjectRole role;
        private String roleDisplayName;
    }
}

package com.autotest.platform.dto;

import com.autotest.platform.entity.Tenant;
import com.fasterxml.jackson.annotation.JsonInclude;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.time.LocalDateTime;

@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
@JsonInclude(JsonInclude.Include.NON_NULL)
public class TenantDTO {

    private Long id;
    private String tenantCode;
    private String tenantName;
    private Tenant.TenantStatus status;
    private Long ownerAdminId;
    private String ownerAdminUsername;
    private Integer memberCount;
    private LocalDateTime createdAt;
    private LocalDateTime updatedAt;
}

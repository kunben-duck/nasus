package com.autotest.platform.dto;

import com.autotest.platform.entity.TenantMembership;
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
public class TenantMembershipDTO {

    private Long id;
    private Long tenantId;
    private Long userId;
    private String username;
    private String fullName;
    private String email;
    private TenantMembership.ProjectRole role;
    private String roleDisplayName;
    private TenantMembership.MembershipStatus status;
    private LocalDateTime createdAt;
    private LocalDateTime updatedAt;
}

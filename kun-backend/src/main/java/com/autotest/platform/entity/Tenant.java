package com.autotest.platform.entity;

import jakarta.persistence.*;
import lombok.*;
import org.hibernate.annotations.CreationTimestamp;
import org.hibernate.annotations.UpdateTimestamp;

import java.time.LocalDateTime;

@Entity
@Table(name = "tenants")
@Data
@NoArgsConstructor
@AllArgsConstructor
@Builder
public class Tenant {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(name = "tenant_code", nullable = false, unique = true, length = 64)
    private String tenantCode;

    @Column(name = "tenant_name", nullable = false, length = 100)
    private String tenantName;

    @ManyToOne(fetch = FetchType.LAZY)
    @JoinColumn(name = "owner_admin_id", nullable = false)
    private User ownerAdmin;

    @Enumerated(EnumType.STRING)
    @Column(nullable = false, length = 32)
    private TenantStatus status = TenantStatus.ACTIVE;

    @CreationTimestamp
    @Column(nullable = false, updatable = false)
    private LocalDateTime createdAt;

    @UpdateTimestamp
    private LocalDateTime updatedAt;

    public enum TenantStatus {
        ACTIVE,
        INACTIVE
    }
}

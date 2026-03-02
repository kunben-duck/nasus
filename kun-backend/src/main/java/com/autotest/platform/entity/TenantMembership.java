package com.autotest.platform.entity;

import jakarta.persistence.*;
import lombok.*;
import org.hibernate.annotations.CreationTimestamp;
import org.hibernate.annotations.UpdateTimestamp;

import java.time.LocalDateTime;

@Entity
@Table(
        name = "tenant_memberships",
        uniqueConstraints = {
                @UniqueConstraint(name = "uk_tenant_membership_tenant_user", columnNames = {"tenant_id", "user_id"})
        }
)
@Data
@NoArgsConstructor
@AllArgsConstructor
@Builder
public class TenantMembership {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @ManyToOne(fetch = FetchType.LAZY)
    @JoinColumn(name = "tenant_id", nullable = false)
    private Tenant tenant;

    @ManyToOne(fetch = FetchType.LAZY)
    @JoinColumn(name = "user_id", nullable = false)
    private User user;

    @Enumerated(EnumType.STRING)
    @Column(nullable = false, length = 64)
    private ProjectRole role = ProjectRole.QA;

    @Enumerated(EnumType.STRING)
    @Column(nullable = false, length = 32)
    private MembershipStatus status = MembershipStatus.ACTIVE;

    @CreationTimestamp
    @Column(nullable = false, updatable = false)
    private LocalDateTime createdAt;

    @UpdateTimestamp
    private LocalDateTime updatedAt;

    public enum MembershipStatus {
        ACTIVE,
        INACTIVE
    }

    public enum ProjectRole {
        TEST_MANAGER,
        TEST_ENGINEER,
        QA,
        // Legacy values kept for backward-compatible deserialization from existing rows.
        SYSTEM_ADMIN,
        TEST_DEVELOPER,
        ADMIN,
        MANAGER,
        USER;

        public ProjectRole canonical() {
            return switch (this) {
                case SYSTEM_ADMIN, ADMIN, MANAGER -> TEST_MANAGER;
                case TEST_DEVELOPER -> TEST_ENGINEER;
                case USER -> QA;
                default -> this;
            };
        }

        public boolean isAssignable() {
            return switch (canonical()) {
                case TEST_MANAGER, TEST_ENGINEER, QA -> true;
                default -> false;
            };
        }

        public String displayName() {
            return switch (canonical()) {
                case TEST_MANAGER -> "测试经理";
                case TEST_ENGINEER -> "测试工程师";
                case QA -> "QA";
                default -> canonical().name();
            };
        }
    }
}

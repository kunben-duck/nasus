package com.autotest.platform.entity;

import jakarta.persistence.*;
import lombok.*;
import org.hibernate.annotations.CreationTimestamp;
import org.hibernate.annotations.UpdateTimestamp;

import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;

@Entity
@Table(name = "users")
@Data
@NoArgsConstructor
@AllArgsConstructor
@Builder
public class User {
    
    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;
    
    @Column(nullable = false, unique = true, length = 50)
    private String username;
    
    @Column(nullable = false, unique = true, length = 100)
    private String email;
    
    @Column(nullable = false)
    private String password;
    
    @Column(length = 100)
    private String fullName;
    
    @Enumerated(EnumType.STRING)
    @Column(nullable = false)
    private UserRole role = UserRole.OPERATIONS_ADMIN;

    @Column(length = 1024)
    private String permissions;
    
    @Enumerated(EnumType.STRING)
    @Column(nullable = false)
    private UserStatus status = UserStatus.ACTIVE;

    @Column(name = "active_tenant_id")
    private Long activeTenantId;
    
    @Column(columnDefinition = "TEXT")
    private String avatar;
    
    @OneToMany(mappedBy = "createdBy", cascade = CascadeType.ALL, fetch = FetchType.LAZY)
    @Builder.Default
    private List<UserStory> userStories = new ArrayList<>();
    
    @OneToMany(mappedBy = "createdBy", cascade = CascadeType.ALL, fetch = FetchType.LAZY)
    @Builder.Default
    private List<TestCase> testCases = new ArrayList<>();
    
    @CreationTimestamp
    @Column(nullable = false, updatable = false)
    private LocalDateTime createdAt;
    
    @UpdateTimestamp
    private LocalDateTime updatedAt;
    
    private LocalDateTime lastLoginAt;
    
    public enum UserRole {
        SYSTEM_ADMIN,
        OPS_ADMIN,
        OPERATIONS_ADMIN,
        // Legacy roles kept for backward compatibility with historical data.
        TEST_MANAGER,
        TEST_DEVELOPER,
        QA,
        ADMIN,
        MANAGER,
        USER;

        public UserRole canonical() {
            return switch (this) {
                case ADMIN -> SYSTEM_ADMIN;
                case MANAGER, TEST_MANAGER -> OPERATIONS_ADMIN;
                case USER, TEST_DEVELOPER, QA -> OPS_ADMIN;
                default -> this;
            };
        }

        public String displayName() {
            return switch (canonical()) {
                case SYSTEM_ADMIN -> "系统管理员";
                case OPS_ADMIN -> "运维管理员";
                case OPERATIONS_ADMIN -> "运营管理员";
                default -> canonical().name();
            };
        }

        public boolean isSystemAdmin() {
            return canonical() == SYSTEM_ADMIN;
        }
    }

    public static List<String> defaultPermissionsByRole(UserRole role) {
        if (role == null) return defaultPermissionsByRole(UserRole.OPERATIONS_ADMIN);
        return switch (role.canonical()) {
            case SYSTEM_ADMIN -> List.of(
                    "ACCOUNT_VIEW",
                    "ACCOUNT_CREATE",
                    "ACCOUNT_UPDATE",
                    "ACCOUNT_DISABLE",
                    "ROLE_ASSIGN",
                    "PERMISSION_ASSIGN",
                    "SETTINGS_MANAGE",
                    "TENANT_MANAGE",
                    "US_MANAGE",
                    "TEST_CASE_MANAGE",
                    "SCRIPT_MANAGE",
                    "EXECUTION_MANAGE",
                    "REPORT_VIEW"
            );
            case OPS_ADMIN -> List.of(
                    "SETTINGS_MANAGE",
                    "US_MANAGE",
                    "TEST_CASE_MANAGE",
                    "SCRIPT_MANAGE",
                    "EXECUTION_MANAGE",
                    "REPORT_VIEW"
            );
            case OPERATIONS_ADMIN -> List.of(
                    "US_MANAGE",
                    "TEST_CASE_MANAGE",
                    "EXECUTION_MANAGE",
                    "REPORT_VIEW"
            );
            default -> Collections.emptyList();
        };
    }
    
    public enum UserStatus {
        ACTIVE, INACTIVE, SUSPENDED
    }
}

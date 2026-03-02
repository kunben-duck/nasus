package com.autotest.platform.config;

import com.autotest.platform.entity.*;
import com.autotest.platform.repository.*;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.boot.CommandLineRunner;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.security.crypto.password.PasswordEncoder;

import java.util.List;
import java.util.Locale;
import java.util.Set;

@Configuration
@RequiredArgsConstructor
@Slf4j
public class DataInitializer {

    private static final String DEFAULT_TENANT_CODE = "KUN";
    private static final String DEFAULT_TENANT_NAME = "kun";

    private final PasswordEncoder passwordEncoder;

    @Bean
    public CommandLineRunner initData(UserRepository userRepository,
                                      TenantRepository tenantRepository,
                                      TenantMembershipRepository tenantMembershipRepository,
                                      UserStoryRepository userStoryRepository,
                                      TestCaseRepository testCaseRepository,
                                      TestScriptRepository testScriptRepository,
                                      TestExecutionRepository testExecutionRepository,
                                      JdbcTemplate jdbcTemplate) {
        return args -> {
            log.info("Initializing sample data...");

            migrateLegacyColumns(jdbcTemplate);

            if (!userRepository.existsByUsername("admin")) {
                User admin = User.builder()
                        .username("admin")
                        .email("admin@autotest.com")
                        .password(passwordEncoder.encode("admin123"))
                        .fullName("Administrator")
                        .role(User.UserRole.SYSTEM_ADMIN)
                        .permissions(String.join(",", User.defaultPermissionsByRole(User.UserRole.SYSTEM_ADMIN)))
                        .status(User.UserStatus.ACTIVE)
                        .build();
                userRepository.save(admin);
                log.info("Created admin user");
            }

            if (!userRepository.existsByUsername("tester")) {
                User tester = User.builder()
                        .username("tester")
                        .email("tester@autotest.com")
                        .password(passwordEncoder.encode("tester123"))
                        .fullName("QA Engineer")
                        .role(User.UserRole.OPS_ADMIN)
                        .permissions(String.join(",", User.defaultPermissionsByRole(User.UserRole.OPS_ADMIN)))
                        .status(User.UserStatus.ACTIVE)
                        .build();
                userRepository.save(tester);
                log.info("Created tester user");
            }

            if (!userRepository.existsByUsername("manager")) {
                User manager = User.builder()
                        .username("manager")
                        .email("manager@autotest.com")
                        .password(passwordEncoder.encode("manager123"))
                        .fullName("Test Manager")
                        .role(User.UserRole.OPERATIONS_ADMIN)
                        .permissions(String.join(",", User.defaultPermissionsByRole(User.UserRole.OPERATIONS_ADMIN)))
                        .status(User.UserStatus.ACTIVE)
                        .build();
                userRepository.save(manager);
                log.info("Created manager user");
            }

            if (!userRepository.existsByUsername("developer")) {
                User developer = User.builder()
                        .username("developer")
                        .email("developer@autotest.com")
                        .password(passwordEncoder.encode("developer123"))
                        .fullName("Test Developer")
                        .role(User.UserRole.OPS_ADMIN)
                        .permissions(String.join(",", User.defaultPermissionsByRole(User.UserRole.OPS_ADMIN)))
                        .status(User.UserStatus.ACTIVE)
                        .build();
                userRepository.save(developer);
                log.info("Created developer user");
            }

            userRepository.findAll().forEach(item -> {
                User.UserRole canonical = item.getRole() == null ? User.UserRole.OPERATIONS_ADMIN : item.getRole().canonical();
                boolean changed = false;
                if (item.getRole() != canonical) {
                    item.setRole(canonical);
                    changed = true;
                }
                if (item.getPermissions() == null || item.getPermissions().trim().isEmpty()) {
                    item.setPermissions(String.join(",", User.defaultPermissionsByRole(canonical)));
                    changed = true;
                }
                if (changed) {
                    userRepository.save(item);
                }
            });

            User admin = userRepository.findByUsername("admin").orElseThrow();

            Tenant defaultTenant = tenantRepository.findByTenantCode(DEFAULT_TENANT_CODE)
                    .orElseGet(() -> {
                        Tenant created = Tenant.builder()
                                .tenantCode(DEFAULT_TENANT_CODE)
                                .tenantName(DEFAULT_TENANT_NAME)
                                .ownerAdmin(admin)
                                .status(Tenant.TenantStatus.ACTIVE)
                                .build();
                        Tenant saved = tenantRepository.save(created);
                        log.info("Created default tenant: {}", saved.getTenantName());
                        return saved;
                    });

            ensureTenantMemberships(userRepository, tenantRepository, tenantMembershipRepository, defaultTenant);
            backfillBusinessTenantData(jdbcTemplate, defaultTenant.getId());

            if (userStoryRepository.countByTenantId(defaultTenant.getId()) == 0) {
                UserStory us1 = UserStory.builder()
                        .usNumber("US-001")
                        .tenantId(defaultTenant.getId())
                        .title("User Login Feature")
                        .description("As a user, I want to login to the system so that I can access my account")
                        .acceptanceCriteria("1. User can enter username and password\n2. System validates credentials\n3. User is redirected to dashboard on success")
                        .priority(UserStory.Priority.HIGH)
                        .status(UserStory.Status.READY)
                        .sprint("Sprint 1")
                        .epic("Authentication")
                        .storyPoints("5")
                        .createdBy(admin)
                        .build();
                userStoryRepository.save(us1);

                UserStory us2 = UserStory.builder()
                        .usNumber("US-002")
                        .tenantId(defaultTenant.getId())
                        .title("Password Reset Feature")
                        .description("As a user, I want to reset my password so that I can regain access")
                        .acceptanceCriteria("1. User can request password reset\n2. System sends reset email\n3. User can set new password")
                        .priority(UserStory.Priority.MEDIUM)
                        .status(UserStory.Status.IN_PROGRESS)
                        .sprint("Sprint 1")
                        .epic("Authentication")
                        .storyPoints("3")
                        .createdBy(admin)
                        .build();
                userStoryRepository.save(us2);

                log.info("Created sample user stories");
            }

            if (testCaseRepository.countByTenantId(defaultTenant.getId()) == 0) {
                UserStory us1 = userStoryRepository.findByUsNumberAndTenantId("US-001", defaultTenant.getId()).orElseThrow();

                TestCase tc1 = TestCase.builder()
                        .caseNumber("TC-001")
                        .tenantId(defaultTenant.getId())
                        .title("Test valid login")
                        .description("Verify user can login with valid credentials")
                        .preconditions("User account exists")
                        .testType(TestCase.TestType.UI)
                        .priority(TestCase.Priority.HIGH)
                        .status(TestCase.Status.READY)
                        .userStory(us1)
                        .createdBy(admin)
                        .tags("login,positive")
                        .build();

                TestStep step1 = TestStep.builder()
                        .stepOrder(1)
                        .action("Navigate to login page")
                        .expectedResult("Login page is displayed")
                        .testCase(tc1)
                        .build();

                TestStep step2 = TestStep.builder()
                        .stepOrder(2)
                        .action("Enter valid username and password")
                        .expectedResult("Credentials are entered")
                        .testCase(tc1)
                        .build();

                TestStep step3 = TestStep.builder()
                        .stepOrder(3)
                        .action("Click login button")
                        .expectedResult("User is redirected to dashboard")
                        .testCase(tc1)
                        .build();

                tc1.setSteps(List.of(step1, step2, step3));
                testCaseRepository.save(tc1);

                TestCase tc2 = TestCase.builder()
                        .caseNumber("TC-002")
                        .tenantId(defaultTenant.getId())
                        .title("Test invalid login")
                        .description("Verify error message for invalid credentials")
                        .preconditions("User account exists")
                        .testType(TestCase.TestType.UI)
                        .priority(TestCase.Priority.HIGH)
                        .status(TestCase.Status.READY)
                        .userStory(us1)
                        .createdBy(admin)
                        .tags("login,negative")
                        .build();
                testCaseRepository.save(tc2);

                log.info("Created sample test cases");
            }

            if (testScriptRepository.countByTenantId(defaultTenant.getId()) == 0) {
                TestCase tc1 = testCaseRepository.findByCaseNumberAndTenantId("TC-001", defaultTenant.getId()).orElseThrow();

                TestScript script1 = TestScript.builder()
                        .tenantId(defaultTenant.getId())
                        .name("Login Test Script")
                        .scriptType(TestScript.ScriptType.PLAYWRIGHT)
                        .language(TestScript.Language.JAVASCRIPT)
                        .code("""
                            const { test, expect } = require('@playwright/test');

                            test('valid login', async ({ page }) => {
                              await page.goto('https://example.com/login');
                              await page.fill('#username', 'testuser');
                              await page.fill('#password', 'password123');
                              await page.click('#login-btn');
                              await expect(page).toHaveURL(/dashboard/);
                            });
                            """)
                        .config("{\"headless\": true, \"browser\": \"chromium\"}")
                        .status(TestScript.Status.READY)
                        .testCase(tc1)
                        .version("1.0.0")
                        .build();
                testScriptRepository.save(script1);

                log.info("Created sample test scripts");
            }

            log.info("Data initialization completed");
        };
    }

    private void ensureTenantMemberships(UserRepository userRepository,
                                         TenantRepository tenantRepository,
                                         TenantMembershipRepository tenantMembershipRepository,
                                         Tenant defaultTenant) {
        Set<String> bootstrapUsers = Set.of("admin", "tester", "manager", "developer");

        userRepository.findAll().forEach(user -> {
            User.UserRole canonicalRole = user.getRole() == null ? User.UserRole.OPERATIONS_ADMIN : user.getRole().canonical();
            List<TenantMembership> activeMemberships = tenantMembershipRepository.findByUserIdAndStatus(
                    user.getId(),
                    TenantMembership.MembershipStatus.ACTIVE
            );
            TenantMembership.ProjectRole mappedProjectRole = mapUserRoleToProjectRole(canonicalRole);

            if (bootstrapUsers.contains(user.getUsername())) {
                upsertDefaultMembership(tenantMembershipRepository, defaultTenant, user, mappedProjectRole);
                if (user.getActiveTenantId() == null) {
                    user.setActiveTenantId(defaultTenant.getId());
                    userRepository.save(user);
                }
                return;
            }

            if (canonicalRole.isSystemAdmin()) {
                if (activeMemberships.isEmpty()) {
                    Tenant personalTenant = tenantRepository.findByOwnerAdminIdOrderByCreatedAtDesc(user.getId())
                            .stream()
                            .findFirst()
                            .orElseGet(() -> createPersonalTenant(tenantRepository, user));
                    TenantMembership membership = tenantMembershipRepository.findByTenantIdAndUserId(personalTenant.getId(), user.getId())
                            .orElseGet(() -> TenantMembership.builder()
                                    .tenant(personalTenant)
                                    .user(user)
                                    .build());
                    membership.setRole(TenantMembership.ProjectRole.TEST_MANAGER);
                    membership.setStatus(TenantMembership.MembershipStatus.ACTIVE);
                    tenantMembershipRepository.save(membership);
                    user.setActiveTenantId(personalTenant.getId());
                    userRepository.save(user);
                } else if (user.getActiveTenantId() == null) {
                    Long fallbackTenantId = activeMemberships.stream()
                            .map(TenantMembership::getTenant)
                            .filter(item -> item != null && item.getStatus() == Tenant.TenantStatus.ACTIVE)
                            .map(Tenant::getId)
                            .findFirst()
                            .orElse(null);
                    if (fallbackTenantId != null) {
                        user.setActiveTenantId(fallbackTenantId);
                        userRepository.save(user);
                    }
                }
                return;
            }

            if (activeMemberships.isEmpty()) {
                upsertDefaultMembership(tenantMembershipRepository, defaultTenant, user, mappedProjectRole);
                user.setActiveTenantId(defaultTenant.getId());
                userRepository.save(user);
            } else if (user.getActiveTenantId() == null) {
                Long fallbackTenantId = activeMemberships.stream()
                        .map(TenantMembership::getTenant)
                        .filter(item -> item != null && item.getStatus() == Tenant.TenantStatus.ACTIVE)
                        .map(Tenant::getId)
                        .findFirst()
                        .orElse(null);
                if (fallbackTenantId != null) {
                    user.setActiveTenantId(fallbackTenantId);
                    userRepository.save(user);
                }
            }
        });
    }

    private void upsertDefaultMembership(TenantMembershipRepository tenantMembershipRepository,
                                         Tenant defaultTenant,
                                         User user,
                                         TenantMembership.ProjectRole role) {
        TenantMembership membership = tenantMembershipRepository.findByTenantIdAndUserId(defaultTenant.getId(), user.getId())
                .orElseGet(() -> TenantMembership.builder()
                        .tenant(defaultTenant)
                        .user(user)
                        .build());
        membership.setRole(role == null ? TenantMembership.ProjectRole.QA : role.canonical());
        membership.setStatus(TenantMembership.MembershipStatus.ACTIVE);
        tenantMembershipRepository.save(membership);
    }

    private TenantMembership.ProjectRole mapUserRoleToProjectRole(User.UserRole role) {
        User.UserRole canonicalRole = role == null ? User.UserRole.OPERATIONS_ADMIN : role.canonical();
        return switch (canonicalRole) {
            case SYSTEM_ADMIN, OPERATIONS_ADMIN -> TenantMembership.ProjectRole.TEST_MANAGER;
            case OPS_ADMIN -> TenantMembership.ProjectRole.TEST_ENGINEER;
            default -> TenantMembership.ProjectRole.QA;
        };
    }

    private Tenant createPersonalTenant(TenantRepository tenantRepository, User user) {
        String normalizedUsername = user.getUsername() == null ? "ADMIN" : user.getUsername()
                .toUpperCase(Locale.ROOT)
                .replaceAll("[^A-Z0-9_-]", "_")
                .replaceAll("_+", "_");
        if (normalizedUsername.isBlank()) {
            normalizedUsername = "ADMIN";
        }
        if (normalizedUsername.length() > 16) {
            normalizedUsername = normalizedUsername.substring(0, 16);
        }

        String baseCode = "TEN_" + normalizedUsername;
        if (baseCode.length() > 32) {
            baseCode = baseCode.substring(0, 32);
        }
        String tenantCode = baseCode;
        int counter = 1;
        while (tenantRepository.existsByTenantCode(tenantCode)) {
            String suffix = "_" + counter++;
            int maxLen = 32 - suffix.length();
            String prefix = maxLen > 0 ? baseCode.substring(0, Math.min(baseCode.length(), maxLen)) : "";
            tenantCode = prefix + suffix;
        }

        String tenantName = (user.getFullName() == null || user.getFullName().isBlank())
                ? user.getUsername() + " Workspace"
                : user.getFullName().trim() + " Workspace";
        if (tenantName.length() > 100) {
            tenantName = tenantName.substring(0, 100);
        }

        return tenantRepository.save(Tenant.builder()
                .tenantCode(tenantCode)
                .tenantName(tenantName)
                .ownerAdmin(user)
                .status(Tenant.TenantStatus.ACTIVE)
                .build());
    }

    private void backfillBusinessTenantData(JdbcTemplate jdbcTemplate, Long tenantId) {
        try {
            jdbcTemplate.update("UPDATE user_stories SET tenant_id = ? WHERE tenant_id IS NULL", tenantId);
        } catch (Exception ex) {
            log.debug("Skip user_stories tenant backfill: {}", ex.getMessage());
        }
        try {
            jdbcTemplate.update("UPDATE test_cases SET tenant_id = ? WHERE tenant_id IS NULL", tenantId);
        } catch (Exception ex) {
            log.debug("Skip test_cases tenant backfill: {}", ex.getMessage());
        }
        try {
            jdbcTemplate.update("UPDATE test_scripts SET tenant_id = ? WHERE tenant_id IS NULL", tenantId);
        } catch (Exception ex) {
            log.debug("Skip test_scripts tenant backfill: {}", ex.getMessage());
        }
        try {
            jdbcTemplate.update("UPDATE test_executions SET tenant_id = ? WHERE tenant_id IS NULL", tenantId);
        } catch (Exception ex) {
            log.debug("Skip test_executions tenant backfill: {}", ex.getMessage());
        }
        try {
            jdbcTemplate.update("UPDATE validation_points SET tenant_id = ? WHERE tenant_id IS NULL", tenantId);
        } catch (Exception ex) {
            log.debug("Skip validation_points tenant backfill: {}", ex.getMessage());
        }
    }

    private void migrateLegacyColumns(JdbcTemplate jdbcTemplate) {
        try {
            jdbcTemplate.execute("ALTER TABLE users MODIFY COLUMN role VARCHAR(64) NOT NULL");
        } catch (Exception ex) {
            log.debug("Skip role column migration: {}", ex.getMessage());
        }
        try {
            jdbcTemplate.execute("ALTER TABLE tenant_memberships MODIFY COLUMN role VARCHAR(64) NOT NULL");
        } catch (Exception ex) {
            log.debug("Skip tenant_memberships.role migration: {}", ex.getMessage());
        }
        try {
            jdbcTemplate.update("UPDATE tenant_memberships SET role = 'TEST_MANAGER' WHERE role IN ('SYSTEM_ADMIN','ADMIN','MANAGER')");
            jdbcTemplate.update("UPDATE tenant_memberships SET role = 'TEST_ENGINEER' WHERE role IN ('TEST_DEVELOPER')");
            jdbcTemplate.update("UPDATE tenant_memberships SET role = 'QA' WHERE role IN ('USER')");
            jdbcTemplate.update("UPDATE tenant_memberships SET role = 'QA' WHERE role IS NULL OR TRIM(role) = ''");
        } catch (Exception ex) {
            log.debug("Skip tenant_memberships role normalization: {}", ex.getMessage());
        }
        try {
            jdbcTemplate.execute("ALTER TABLE users MODIFY COLUMN status VARCHAR(32) NOT NULL");
        } catch (Exception ex) {
            log.debug("Skip status column migration: {}", ex.getMessage());
        }
        try {
            jdbcTemplate.execute("ALTER TABLE user_stories MODIFY COLUMN status VARCHAR(32) NOT NULL");
        } catch (Exception ex) {
            log.debug("Skip user_stories.status column migration: {}", ex.getMessage());
        }
        try {
            jdbcTemplate.execute("ALTER TABLE users MODIFY COLUMN avatar TEXT");
        } catch (Exception ex) {
            log.debug("Skip avatar column migration: {}", ex.getMessage());
        }
        try {
            jdbcTemplate.execute("ALTER TABLE user_stories MODIFY COLUMN latest_analysis_payload LONGTEXT");
        } catch (Exception ex) {
            log.debug("Skip latest_analysis_payload column migration: {}", ex.getMessage());
        }
        try {
            jdbcTemplate.execute("ALTER TABLE user_stories MODIFY COLUMN latest_case_generation_payload LONGTEXT");
        } catch (Exception ex) {
            log.debug("Skip latest_case_generation_payload column migration: {}", ex.getMessage());
        }
        try {
            jdbcTemplate.execute("ALTER TABLE execution_timeline MODIFY COLUMN screenshot_path LONGTEXT");
        } catch (Exception ex) {
            log.debug("Skip execution_timeline.screenshot_path migration: {}", ex.getMessage());
        }
        try {
            jdbcTemplate.execute("ALTER TABLE execution_screenshots MODIFY COLUMN file_path LONGTEXT");
        } catch (Exception ex) {
            log.debug("Skip execution_screenshots.file_path migration: {}", ex.getMessage());
        }

        try {
            jdbcTemplate.execute("ALTER TABLE users ADD COLUMN active_tenant_id BIGINT");
        } catch (Exception ex) {
            log.debug("Skip users.active_tenant_id migration: {}", ex.getMessage());
        }
        try {
            jdbcTemplate.execute("ALTER TABLE user_stories ADD COLUMN tenant_id BIGINT");
        } catch (Exception ex) {
            log.debug("Skip user_stories.tenant_id migration: {}", ex.getMessage());
        }
        try {
            jdbcTemplate.execute("ALTER TABLE test_cases ADD COLUMN tenant_id BIGINT");
        } catch (Exception ex) {
            log.debug("Skip test_cases.tenant_id migration: {}", ex.getMessage());
        }
        try {
            jdbcTemplate.execute("ALTER TABLE test_scripts ADD COLUMN tenant_id BIGINT");
        } catch (Exception ex) {
            log.debug("Skip test_scripts.tenant_id migration: {}", ex.getMessage());
        }
        try {
            jdbcTemplate.execute("ALTER TABLE test_executions ADD COLUMN tenant_id BIGINT");
        } catch (Exception ex) {
            log.debug("Skip test_executions.tenant_id migration: {}", ex.getMessage());
        }
        try {
            jdbcTemplate.execute("ALTER TABLE validation_points ADD COLUMN tenant_id BIGINT");
        } catch (Exception ex) {
            log.debug("Skip validation_points.tenant_id migration: {}", ex.getMessage());
        }
    }
}

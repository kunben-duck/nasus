package com.autotest.platform.service;

import com.autotest.platform.dto.TestCaseDTO;
import com.autotest.platform.dto.UserDTO;
import com.autotest.platform.dto.UserStoryDTO;
import com.autotest.platform.entity.TestCase;
import com.autotest.platform.entity.TestStep;
import com.autotest.platform.entity.User;
import com.autotest.platform.entity.UserStory;
import com.autotest.platform.repository.TestCaseRepository;
import com.autotest.platform.repository.TestScriptGenerationRecordRepository;
import com.autotest.platform.repository.UserRepository;
import com.autotest.platform.repository.UserStoryRepository;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.cache.annotation.CacheEvict;
import org.springframework.cache.annotation.Cacheable;
import org.springframework.data.domain.Page;
import org.springframework.data.domain.Pageable;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.ArrayList;
import java.util.List;
import java.util.UUID;
import java.util.stream.Collectors;

@Service
@RequiredArgsConstructor
@Slf4j
public class TestCaseService {

    private final TestCaseRepository testCaseRepository;
    private final TestScriptGenerationRecordRepository generationRecordRepository;
    private final UserRepository userRepository;
    private final UserStoryRepository userStoryRepository;
    private final TenantContextService tenantContextService;

    @Cacheable(value = "testCases", key = "#id")
    @Transactional(readOnly = true)
    public TestCaseDTO getTestCaseById(Long id) {
        Long tenantId = tenantContextService.requireCurrentTenantId();
        TestCase tc = testCaseRepository.findByIdAndTenantId(id, tenantId)
                .orElseThrow(() -> new RuntimeException("Test Case not found: " + id));
        return mapToDTO(tc);
    }

    @Transactional(readOnly = true)
    public TestCaseDTO getTestCaseByNumber(String caseNumber) {
        Long tenantId = tenantContextService.requireCurrentTenantId();
        TestCase tc = testCaseRepository.findByCaseNumberAndTenantId(caseNumber, tenantId)
                .orElseThrow(() -> new RuntimeException("Test Case not found: " + caseNumber));
        return mapToDTO(tc);
    }

    @Transactional(readOnly = true)
    public Page<TestCaseDTO> getAllTestCases(Pageable pageable) {
        Long tenantId = tenantContextService.requireCurrentTenantId();
        return testCaseRepository.findByTenantId(tenantId, pageable).map(this::mapToDTO);
    }

    @Transactional(readOnly = true)
    public Page<TestCaseDTO> getTestCasesByFilters(
            String keyword,
            TestCase.Status status,
            TestCase.TestType type,
            TestCase.Priority priority,
            Pageable pageable) {
        Long tenantId = tenantContextService.requireCurrentTenantId();
        return testCaseRepository.findByFilters(tenantId, keyword, status, type, priority, pageable).map(this::mapToDTO);
    }

    @Transactional(readOnly = true)
    public Page<TestCaseDTO> searchTestCases(String keyword, Pageable pageable) {
        Long tenantId = tenantContextService.requireCurrentTenantId();
        return testCaseRepository.searchTestCases(tenantId, keyword, pageable).map(this::mapToDTO);
    }

    @Transactional(readOnly = true)
    public Page<TestCaseDTO> getTestCasesByStatus(TestCase.Status status, Pageable pageable) {
        Long tenantId = tenantContextService.requireCurrentTenantId();
        return testCaseRepository.findByStatus(tenantId, status, pageable).map(this::mapToDTO);
    }

    @Transactional(readOnly = true)
    public List<TestCaseDTO> getTestCasesByUserStory(Long usId) {
        Long tenantId = tenantContextService.requireCurrentTenantId();
        return testCaseRepository.findByUserStoryId(tenantId, usId).stream()
                .map(this::mapToDTO)
                .collect(Collectors.toList());
    }

    @Transactional
    @CacheEvict(value = "testCases", allEntries = true)
    public TestCaseDTO createTestCase(TestCaseDTO.CreateRequest request, String username) {
        TenantContextService.CurrentTenant currentTenant = tenantContextService.resolveCurrentTenant(username);
        Long tenantId = currentTenant.tenant().getId();

        User user = userRepository.findByUsername(username)
                .orElseThrow(() -> new RuntimeException("User not found: " + username));

        UserStory us = null;
        if (request.getUserStoryId() != null) {
            us = userStoryRepository.findByIdAndTenantId(request.getUserStoryId(), tenantId)
                    .orElseThrow(() -> new RuntimeException("User Story not found: " + request.getUserStoryId()));
        }

        String caseNumber = "TC-" + UUID.randomUUID().toString().substring(0, 8).toUpperCase();

        TestCase tc = TestCase.builder()
                .caseNumber(caseNumber)
                .tenantId(tenantId)
                .title(request.getTitle())
                .description(request.getDescription())
                .preconditions(request.getPreconditions())
                .testType(request.getTestType() != null ?
                        TestCase.TestType.valueOf(request.getTestType().name()) : TestCase.TestType.FUNCTIONAL)
                .priority(request.getPriority() != null ?
                        TestCase.Priority.valueOf(request.getPriority().name()) : TestCase.Priority.MEDIUM)
                .status(TestCase.Status.DRAFT)
                .userStory(us)
                .createdBy(user)
                .tags(request.getTags())
                .build();

        if (request.getSteps() != null && !request.getSteps().isEmpty()) {
            List<TestCaseDTO.TestStepDTO> normalizedSteps = normalizeStepDtos(request.getSteps());
            List<TestStep> steps = normalizedSteps.stream()
                    .map(stepDTO -> TestStep.builder()
                            .stepOrder(stepDTO.getStepOrder())
                            .action(stepDTO.getAction())
                            .expectedResult(stepDTO.getExpectedResult())
                            .testData(stepDTO.getTestData())
                            .testCase(tc)
                            .build())
                    .collect(Collectors.toList());
            tc.setSteps(steps);
        }

        TestCase savedTc = testCaseRepository.save(tc);
        log.info("Created Test Case: {} (tenantId={})", savedTc.getCaseNumber(), tenantId);
        return mapToDTO(savedTc);
    }

    @Transactional
    @CacheEvict(value = "testCases", key = "#id")
    public TestCaseDTO updateTestCase(Long id, TestCaseDTO.UpdateRequest request) {
        Long tenantId = tenantContextService.requireCurrentTenantId();
        TestCase tc = testCaseRepository.findByIdAndTenantId(id, tenantId)
                .orElseThrow(() -> new RuntimeException("Test Case not found: " + id));

        if (request.getTitle() != null) {
            tc.setTitle(request.getTitle());
        }
        if (request.getDescription() != null) {
            tc.setDescription(request.getDescription());
        }
        if (request.getPreconditions() != null) {
            tc.setPreconditions(request.getPreconditions());
        }
        if (request.getTestType() != null) {
            tc.setTestType(TestCase.TestType.valueOf(request.getTestType().name()));
        }
        if (request.getPriority() != null) {
            tc.setPriority(TestCase.Priority.valueOf(request.getPriority().name()));
        }
        if (request.getStatus() != null) {
            tc.setStatus(TestCase.Status.valueOf(request.getStatus().name()));
        }
        if (request.getTags() != null) {
            tc.setTags(request.getTags());
        }

        if (request.getSteps() != null) {
            tc.getSteps().clear();
            List<TestCaseDTO.TestStepDTO> normalizedSteps = normalizeStepDtos(request.getSteps());
            List<TestStep> steps = normalizedSteps.stream()
                    .map(stepDTO -> TestStep.builder()
                            .stepOrder(stepDTO.getStepOrder())
                            .action(stepDTO.getAction())
                            .expectedResult(stepDTO.getExpectedResult())
                            .testData(stepDTO.getTestData())
                            .testCase(tc)
                            .build())
                    .collect(Collectors.toList());
            tc.getSteps().addAll(steps);
        }

        TestCase updatedTc = testCaseRepository.save(tc);
        log.info("Updated Test Case: {}", updatedTc.getCaseNumber());
        return mapToDTO(updatedTc);
    }

    @Transactional
    @CacheEvict(value = "testCases", key = "#id")
    public void deleteTestCase(Long id) {
        Long tenantId = tenantContextService.requireCurrentTenantId();
        TestCase tc = testCaseRepository.findByIdAndTenantId(id, tenantId)
                .orElseThrow(() -> new RuntimeException("Test Case not found: " + id));
        generationRecordRepository.deleteByTenantIdAndTestCaseId(tenantId, tc.getId());
        testCaseRepository.delete(tc);
        log.info("Deleted Test Case: {}", tc.getCaseNumber());
    }

    @Transactional(readOnly = true)
    public long countTestCases() {
        Long tenantId = tenantContextService.requireCurrentTenantId();
        return testCaseRepository.countByTenantId(tenantId);
    }

    @Transactional(readOnly = true)
    public long countByStatus(TestCase.Status status) {
        Long tenantId = tenantContextService.requireCurrentTenantId();
        return testCaseRepository.countByStatus(tenantId, status);
    }

    private List<TestCaseDTO.TestStepDTO> normalizeStepDtos(List<TestCaseDTO.TestStepDTO> rawSteps) {
        if (rawSteps == null || rawSteps.isEmpty()) {
            return List.of();
        }
        List<TestCaseDTO.TestStepDTO> normalized = reindexSteps(rawSteps);
        while (isExactRepeat(normalized)) {
            normalized = reindexSteps(new ArrayList<>(normalized.subList(0, normalized.size() / 2)));
        }
        return normalized;
    }

    private List<TestCaseDTO.TestStepDTO> reindexSteps(List<TestCaseDTO.TestStepDTO> rawSteps) {
        List<TestCaseDTO.TestStepDTO> normalized = new ArrayList<>();
        for (TestCaseDTO.TestStepDTO step : rawSteps) {
            if (step == null) continue;
            String action = normalizeStepField(step.getAction());
            String expected = normalizeStepField(step.getExpectedResult());
            String data = normalizeStepField(step.getTestData());
            if (action.isEmpty() && expected.isEmpty() && data.isEmpty()) {
                continue;
            }
            normalized.add(TestCaseDTO.TestStepDTO.builder()
                    .stepOrder(normalized.size() + 1)
                    .action(action.isEmpty() ? "步骤 " + (normalized.size() + 1) : action)
                    .expectedResult(expected.isEmpty() ? "执行成功" : expected)
                    .testData(data)
                    .build());
        }
        return normalized;
    }

    private boolean isExactRepeat(List<TestCaseDTO.TestStepDTO> steps) {
        if (steps == null || steps.size() < 2 || steps.size() % 2 != 0) {
            return false;
        }
        int half = steps.size() / 2;
        for (int i = 0; i < half; i++) {
            TestCaseDTO.TestStepDTO left = steps.get(i);
            TestCaseDTO.TestStepDTO right = steps.get(i + half);
            if (!normalizeStepField(left.getAction()).equals(normalizeStepField(right.getAction()))) {
                return false;
            }
            if (!normalizeStepField(left.getExpectedResult()).equals(normalizeStepField(right.getExpectedResult()))) {
                return false;
            }
            if (!normalizeStepField(left.getTestData()).equals(normalizeStepField(right.getTestData()))) {
                return false;
            }
        }
        return true;
    }

    private String normalizeStepField(String value) {
        return value == null ? "" : value.trim();
    }

    private TestCaseDTO mapToDTO(TestCase tc) {
        return TestCaseDTO.builder()
                .id(tc.getId())
                .caseNumber(tc.getCaseNumber())
                .title(tc.getTitle())
                .description(tc.getDescription())
                .preconditions(tc.getPreconditions())
                .testType(TestCaseDTO.TestType.valueOf(tc.getTestType().name()))
                .priority(TestCaseDTO.Priority.valueOf(tc.getPriority().name()))
                .status(TestCaseDTO.Status.valueOf(tc.getStatus().name()))
                .userStory(mapUserStory(tc.getUserStory()))
                .createdBy(mapUser(tc.getCreatedBy()))
                .steps(tc.getSteps() == null ? List.of() : tc.getSteps().stream()
                        .map(step -> TestCaseDTO.TestStepDTO.builder()
                                .stepOrder(step.getStepOrder())
                                .action(step.getAction())
                                .expectedResult(step.getExpectedResult())
                                .testData(step.getTestData())
                                .build())
                        .collect(Collectors.toList()))
                .hasScript(tc.getTestScript() != null)
                .executionCount(tc.getExecutions() != null ? tc.getExecutions().size() : 0)
                .tags(tc.getTags())
                .createdAt(tc.getCreatedAt())
                .updatedAt(tc.getUpdatedAt())
                .build();
    }

    private UserStoryDTO mapUserStory(UserStory userStory) {
        if (userStory == null) {
            return null;
        }
        return UserStoryDTO.builder()
                .id(userStory.getId())
                .usNumber(userStory.getUsNumber())
                .title(userStory.getTitle())
                .status(userStory.getStatus())
                .priority(userStory.getPriority())
                .tenantId(userStory.getTenantId())
                .build();
    }

    private UserDTO mapUser(User user) {
        if (user == null) {
            return null;
        }
        return UserDTO.builder()
                .id(user.getId())
                .username(user.getUsername())
                .email(user.getEmail())
                .fullName(user.getFullName())
                .role(user.getRole())
                .status(user.getStatus())
                .activeTenantId(user.getActiveTenantId())
                .build();
    }
}

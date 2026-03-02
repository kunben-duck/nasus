package com.autotest.platform.service;

import com.autotest.platform.dto.TestCaseDTO;
import com.autotest.platform.dto.TestScriptDTO;
import com.autotest.platform.entity.TestCase;
import com.autotest.platform.entity.TestScript;
import com.autotest.platform.repository.TestCaseRepository;
import com.autotest.platform.repository.TestScriptGenerationRecordRepository;
import com.autotest.platform.repository.TestScriptRepository;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.cache.annotation.CacheEvict;
import org.springframework.cache.annotation.Cacheable;
import org.springframework.data.domain.Page;
import org.springframework.data.domain.Pageable;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.List;
import java.util.stream.Collectors;

@Service
@RequiredArgsConstructor
@Slf4j
public class TestScriptService {

    private final TestScriptRepository testScriptRepository;
    private final TestCaseRepository testCaseRepository;
    private final TestScriptGenerationRecordRepository generationRecordRepository;
    private final TenantContextService tenantContextService;

    @Cacheable(value = "testScripts", key = "#id")
    @Transactional(readOnly = true)
    public TestScriptDTO getTestScriptById(Long id) {
        Long tenantId = tenantContextService.requireCurrentTenantId();
        TestScript script = testScriptRepository.findByIdAndTenantId(id, tenantId)
                .orElseThrow(() -> new RuntimeException("Test Script not found: " + id));
        return mapToDTO(script);
    }

    @Transactional(readOnly = true)
    public TestScriptDTO getTestScriptByTestCaseId(Long testCaseId) {
        Long tenantId = tenantContextService.requireCurrentTenantId();
        TestScript script = testScriptRepository.findByTestCaseIdAndTenantId(testCaseId, tenantId)
                .orElseThrow(() -> new RuntimeException("Test Script not found for test case: " + testCaseId));
        return mapToDTO(script);
    }

    @Transactional(readOnly = true)
    public Page<TestScriptDTO> getAllTestScripts(Pageable pageable) {
        Long tenantId = tenantContextService.requireCurrentTenantId();
        return testScriptRepository.findByTenantId(tenantId, pageable).map(this::mapToDTO);
    }

    @Transactional(readOnly = true)
    public Page<TestScriptDTO> getTestScriptsByType(TestScript.ScriptType type, Pageable pageable) {
        Long tenantId = tenantContextService.requireCurrentTenantId();
        return testScriptRepository.findByScriptType(tenantId, type, pageable).map(this::mapToDTO);
    }

    @Transactional
    @CacheEvict(value = "testScripts", allEntries = true)
    public TestScriptDTO createTestScript(TestScriptDTO.CreateRequest request) {
        Long tenantId = tenantContextService.requireCurrentTenantId();
        TestCase testCase = testCaseRepository.findByIdAndTenantId(request.getTestCaseId(), tenantId)
                .orElseThrow(() -> new RuntimeException("Test Case not found: " + request.getTestCaseId()));

        if (testScriptRepository.findByTestCaseIdAndTenantId(request.getTestCaseId(), tenantId).isPresent()) {
            throw new RuntimeException("Test Script already exists for this test case");
        }

        TestScript script = TestScript.builder()
                .tenantId(tenantId)
                .name(request.getName())
                .scriptType(request.getScriptType() != null ?
                        TestScript.ScriptType.valueOf(request.getScriptType().name()) : TestScript.ScriptType.PLAYWRIGHT)
                .language(request.getLanguage() != null ?
                        TestScript.Language.valueOf(request.getLanguage().name()) : TestScript.Language.JAVASCRIPT)
                .code(request.getCode())
                .config(request.getConfig())
                .status(TestScript.Status.DRAFT)
                .testCase(testCase)
                .version("1.0.0")
                .build();

        TestScript savedScript = testScriptRepository.save(script);
        log.info("Created Test Script: {}", savedScript.getName());
        return mapToDTO(savedScript);
    }

    @Transactional
    @CacheEvict(value = "testScripts", key = "#id")
    public TestScriptDTO updateTestScript(Long id, TestScriptDTO.UpdateRequest request) {
        Long tenantId = tenantContextService.requireCurrentTenantId();
        TestScript script = testScriptRepository.findByIdAndTenantId(id, tenantId)
                .orElseThrow(() -> new RuntimeException("Test Script not found: " + id));

        if (request.getName() != null) {
            script.setName(request.getName());
        }
        if (request.getCode() != null) {
            script.setCode(request.getCode());
        }
        if (request.getConfig() != null) {
            script.setConfig(request.getConfig());
        }
        if (request.getStatus() != null) {
            script.setStatus(TestScript.Status.valueOf(request.getStatus().name()));
        }

        TestScript updatedScript = testScriptRepository.save(script);
        log.info("Updated Test Script: {}", updatedScript.getName());
        return mapToDTO(updatedScript);
    }

    @Transactional
    @CacheEvict(value = "testScripts", key = "#id")
    public void deleteTestScript(Long id) {
        Long tenantId = tenantContextService.requireCurrentTenantId();
        TestScript script = testScriptRepository.findByIdAndTenantId(id, tenantId)
                .orElseThrow(() -> new RuntimeException("Test Script not found: " + id));
        generationRecordRepository.clearScriptReferenceByScriptId(tenantId, script.getId());
        testScriptRepository.delete(script);
        log.info("Deleted Test Script: {}", script.getName());
    }

    @Transactional(readOnly = true)
    public List<TestScriptDTO> getScriptsByStatus(TestScript.Status status) {
        Long tenantId = tenantContextService.requireCurrentTenantId();
        return testScriptRepository.findByStatus(tenantId, status).stream()
                .map(this::mapToDTO)
                .collect(Collectors.toList());
    }

    @Transactional(readOnly = true)
    public long countTestScripts() {
        Long tenantId = tenantContextService.requireCurrentTenantId();
        return testScriptRepository.countByTenantId(tenantId);
    }

    @Transactional(readOnly = true)
    public long countByStatus(TestScript.Status status) {
        Long tenantId = tenantContextService.requireCurrentTenantId();
        return testScriptRepository.countByStatus(tenantId, status);
    }

    @Transactional
    @CacheEvict(value = "testScripts", allEntries = true)
    public TestScriptDTO saveGeneratedScript(Long testCaseId,
                                             TestScriptDTO.ScriptType scriptType,
                                             TestScriptDTO.Language language,
                                             String code) {
        Long tenantId = tenantContextService.requireCurrentTenantId();
        TestCase testCase = testCaseRepository.findByIdAndTenantId(testCaseId, tenantId)
                .orElseThrow(() -> new RuntimeException("Test Case not found: " + testCaseId));

        TestScript script = testScriptRepository.findByTestCaseIdAndTenantId(testCaseId, tenantId)
                .orElse(TestScript.builder()
                        .tenantId(tenantId)
                        .name(testCase.getTitle() + " - AI Script")
                        .testCase(testCase)
                        .version("1.0.0")
                        .build());

        script.setTenantId(tenantId);
        script.setScriptType(scriptType != null
                ? TestScript.ScriptType.valueOf(scriptType.name())
                : TestScript.ScriptType.PLAYWRIGHT);
        script.setLanguage(language != null
                ? TestScript.Language.valueOf(language.name())
                : TestScript.Language.JAVASCRIPT);
        script.setCode(code);
        script.setStatus(TestScript.Status.READY);
        if (script.getName() == null || script.getName().isBlank()) {
            script.setName(testCase.getTitle() + " - AI Script");
        }

        TestScript saved = testScriptRepository.save(script);
        return mapToDTO(saved);
    }

    private TestScriptDTO mapToDTO(TestScript script) {
        return TestScriptDTO.builder()
                .id(script.getId())
                .name(script.getName())
                .scriptType(TestScriptDTO.ScriptType.valueOf(script.getScriptType().name()))
                .language(TestScriptDTO.Language.valueOf(script.getLanguage().name()))
                .code(script.getCode())
                .config(script.getConfig())
                .status(TestScriptDTO.Status.valueOf(script.getStatus().name()))
                .testCase(mapTestCase(script.getTestCase()))
                .version(script.getVersion())
                .filePath(script.getFilePath())
                .createdAt(script.getCreatedAt())
                .updatedAt(script.getUpdatedAt())
                .build();
    }

    private TestCaseDTO mapTestCase(TestCase testCase) {
        if (testCase == null) {
            return null;
        }
        return TestCaseDTO.builder()
                .id(testCase.getId())
                .caseNumber(testCase.getCaseNumber())
                .title(testCase.getTitle())
                .status(TestCaseDTO.Status.valueOf(testCase.getStatus().name()))
                .priority(TestCaseDTO.Priority.valueOf(testCase.getPriority().name()))
                .testType(TestCaseDTO.TestType.valueOf(testCase.getTestType().name()))
                .build();
    }
}

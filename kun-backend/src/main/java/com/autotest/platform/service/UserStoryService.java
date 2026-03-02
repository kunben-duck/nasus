package com.autotest.platform.service;

import com.autotest.platform.dto.UserDTO;
import com.autotest.platform.dto.UserStoryDTO;
import com.autotest.platform.entity.Tenant;
import com.autotest.platform.entity.User;
import com.autotest.platform.entity.UserStory;
import com.autotest.platform.entity.ValidationPoint;
import com.autotest.platform.repository.TenantRepository;
import com.autotest.platform.repository.TestCaseRepository;
import com.autotest.platform.repository.UserRepository;
import com.autotest.platform.repository.TestScriptGenerationRecordRepository;
import com.autotest.platform.repository.UserStoryRepository;
import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.cache.annotation.CacheEvict;
import org.springframework.cache.annotation.Cacheable;
import org.springframework.data.domain.Page;
import org.springframework.data.domain.Pageable;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.LocalDateTime;
import java.util.EnumSet;
import java.util.List;
import java.util.Optional;
import java.util.Set;
import java.util.stream.Collectors;

@Service
@RequiredArgsConstructor
@Slf4j
public class UserStoryService {

    private final UserStoryRepository userStoryRepository;
    private final TestScriptGenerationRecordRepository generationRecordRepository;
    private final UserRepository userRepository;
    private final TenantRepository tenantRepository;
    private final TestCaseRepository testCaseRepository;
    private final TenantContextService tenantContextService;
    private final ObjectMapper objectMapper;

    @Cacheable(value = "userStories", key = "#id")
    @Transactional(readOnly = true)
    public UserStoryDTO getUserStoryById(Long id) {
        Long tenantId = tenantContextService.requireCurrentTenantId();
        UserStory us = userStoryRepository.findByIdAndTenantId(id, tenantId)
                .orElseThrow(() -> new RuntimeException("User Story not found: " + id));
        return mapToDTO(us);
    }

    @Transactional(readOnly = true)
    public UserStoryDTO getUserStoryByNumber(String usNumber) {
        Long tenantId = tenantContextService.requireCurrentTenantId();
        UserStory us = userStoryRepository.findByUsNumberAndTenantId(usNumber, tenantId)
                .orElseThrow(() -> new RuntimeException("User Story not found: " + usNumber));
        return mapToDTO(us);
    }

    @Transactional(readOnly = true)
    public Page<UserStoryDTO> getAllUserStories(Pageable pageable) {
        Long tenantId = tenantContextService.requireCurrentTenantId();
        return userStoryRepository.findByTenantId(tenantId, pageable).map(this::mapToDTO);
    }

    @Transactional(readOnly = true)
    public Page<UserStoryDTO> getUserStoriesByFilters(
            String keyword,
            UserStory.Status status,
            UserStory.Priority priority,
            String sprint,
            Pageable pageable) {
        Long tenantId = tenantContextService.requireCurrentTenantId();
        return userStoryRepository.findByFilters(tenantId, keyword, status, priority, sprint, pageable).map(this::mapToDTO);
    }

    @Transactional(readOnly = true)
    public Page<UserStoryDTO> searchUserStories(String keyword, Pageable pageable) {
        Long tenantId = tenantContextService.requireCurrentTenantId();
        return userStoryRepository.searchUserStories(tenantId, keyword, pageable).map(this::mapToDTO);
    }

    @Transactional(readOnly = true)
    public Page<UserStoryDTO> getUserStoriesByStatus(UserStory.Status status, Pageable pageable) {
        Long tenantId = tenantContextService.requireCurrentTenantId();
        return userStoryRepository.findByStatusAndTenantId(tenantId, status, pageable).map(this::mapToDTO);
    }

    @Transactional
    @CacheEvict(value = "userStories", allEntries = true)
    public UserStoryDTO createUserStory(UserStoryDTO.CreateRequest request, String username) {
        TenantContextService.CurrentTenant currentTenant = tenantContextService.resolveCurrentTenant(username);
        User user = userRepository.findByUsername(username)
                .orElseThrow(() -> new RuntimeException("User not found: " + username));

        Long tenantId = currentTenant.tenant().getId();
        if (userStoryRepository.existsByUsNumberAndTenantId(request.getUsNumber(), tenantId)) {
            throw new RuntimeException("User Story number already exists: " + request.getUsNumber());
        }

        UserStory us = UserStory.builder()
                .usNumber(request.getUsNumber())
                .tenantId(tenantId)
                .title(request.getTitle())
                .description(request.getDescription())
                .acceptanceCriteria(request.getAcceptanceCriteria())
                .priority(request.getPriority() != null ? request.getPriority() : UserStory.Priority.MEDIUM)
                .status(UserStory.Status.DRAFT)
                .sprint(request.getSprint())
                .epic(request.getEpic())
                .storyPoints(request.getStoryPoints())
                .createdBy(user)
                .build();

        UserStory savedUs = userStoryRepository.save(us);
        log.info("Created User Story: {} (tenantId={})", savedUs.getUsNumber(), tenantId);
        return mapToDTO(savedUs);
    }

    @Transactional
    @CacheEvict(value = "userStories", key = "#id")
    public UserStoryDTO updateUserStory(Long id, UserStoryDTO.UpdateRequest request) {
        Long tenantId = tenantContextService.requireCurrentTenantId();
        UserStory us = userStoryRepository.findByIdAndTenantId(id, tenantId)
                .orElseThrow(() -> new RuntimeException("User Story not found: " + id));

        if (request.getTitle() != null) {
            us.setTitle(request.getTitle());
        }
        if (request.getDescription() != null) {
            us.setDescription(request.getDescription());
        }
        if (request.getAcceptanceCriteria() != null) {
            us.setAcceptanceCriteria(request.getAcceptanceCriteria());
        }
        if (request.getPriority() != null) {
            us.setPriority(request.getPriority());
        }
        if (request.getStatus() != null) {
            UserStory.Status currentStatus = us.getStatus();
            UserStory.Status requestedStatus = request.getStatus();
            if (requestedStatus != currentStatus) {
                if (requestedStatus == UserStory.Status.ARCHIVED) {
                    if (currentStatus != UserStory.Status.DONE && currentStatus != UserStory.Status.ARCHIVED) {
                        throw new RuntimeException("US 仅在执行完毕后允许手动归档");
                    }
                    us.setStatus(UserStory.Status.ARCHIVED);
                } else {
                    throw new RuntimeException("US 状态由流程自动流转，手动仅支持归档");
                }
            }
        }
        if (request.getSprint() != null) {
            us.setSprint(request.getSprint());
        }
        if (request.getEpic() != null) {
            us.setEpic(request.getEpic());
        }
        if (request.getStoryPoints() != null) {
            us.setStoryPoints(request.getStoryPoints());
        }

        UserStory updatedUs = userStoryRepository.save(us);
        log.info("Updated User Story: {}", updatedUs.getUsNumber());
        return mapToDTO(updatedUs);
    }

    @Transactional
    @CacheEvict(value = "userStories", key = "#id")
    public void deleteUserStory(Long id) {
        Long tenantId = tenantContextService.requireCurrentTenantId();
        UserStory us = userStoryRepository.findByIdAndTenantId(id, tenantId)
                .orElseThrow(() -> new RuntimeException("User Story not found: " + id));
        generationRecordRepository.deleteByTenantIdAndUserStoryId(tenantId, us.getId());
        userStoryRepository.delete(us);
        log.info("Deleted User Story: {}", us.getUsNumber());
    }

    @Transactional
    @CacheEvict(value = "userStories", key = "#userStoryId")
    public void transitionWorkflowStatus(Long userStoryId, UserStory.Status targetStatus) {
        if (targetStatus == null) {
            return;
        }
        UserStory us = findUserStoryForBackgroundUpdate(userStoryId);
        UserStory.Status currentStatus = us.getStatus();
        if (currentStatus == targetStatus) {
            return;
        }
        if (currentStatus == UserStory.Status.ARCHIVED && targetStatus != UserStory.Status.ARCHIVED) {
            log.info("Skip workflow transition for archived US: {} current={} target={}",
                    us.getUsNumber(), currentStatus, targetStatus);
            return;
        }

        us.setStatus(targetStatus);
        userStoryRepository.save(us);
        log.info("Workflow transitioned US {} status: {} -> {}",
                us.getUsNumber(), currentStatus, targetStatus);
    }

    @Transactional
    @CacheEvict(value = "userStories", key = "#userStoryId")
    public boolean transitionWorkflowStatusIfCurrent(
            Long userStoryId,
            Set<UserStory.Status> allowedCurrentStatuses,
            UserStory.Status targetStatus) {
        if (targetStatus == null) {
            return false;
        }

        UserStory us = findUserStoryForBackgroundUpdate(userStoryId);
        UserStory.Status currentStatus = us.getStatus();
        if (currentStatus == targetStatus) {
            return true;
        }
        if (currentStatus == UserStory.Status.ARCHIVED && targetStatus != UserStory.Status.ARCHIVED) {
            log.info("Skip conditional transition for archived US: {} current={} target={}",
                    us.getUsNumber(), currentStatus, targetStatus);
            return false;
        }

        Set<UserStory.Status> allowed = allowedCurrentStatuses == null
                ? EnumSet.noneOf(UserStory.Status.class)
                : (allowedCurrentStatuses.isEmpty()
                    ? EnumSet.noneOf(UserStory.Status.class)
                    : EnumSet.copyOf(allowedCurrentStatuses));
        if (!allowed.isEmpty() && !allowed.contains(currentStatus)) {
            log.info("Skip conditional transition for US {}: current={} not in allowed={}, target={}",
                    us.getUsNumber(), currentStatus, allowed, targetStatus);
            return false;
        }

        us.setStatus(targetStatus);
        userStoryRepository.save(us);
        log.info("Conditionally transitioned US {} status: {} -> {}",
                us.getUsNumber(), currentStatus, targetStatus);
        return true;
    }

    @Transactional(readOnly = true)
    public List<UserStoryDTO> getUserStoriesBySprint(String sprint) {
        Long tenantId = tenantContextService.requireCurrentTenantId();
        return userStoryRepository.findBySprintAndTenantId(tenantId, sprint).stream()
                .map(this::mapToDTO)
                .collect(Collectors.toList());
    }

    @Transactional(readOnly = true)
    public List<String> getAllSprints() {
        Long tenantId = tenantContextService.requireCurrentTenantId();
        return userStoryRepository.findAllSprints(tenantId);
    }

    @Transactional(readOnly = true)
    public long countUserStories() {
        Long tenantId = tenantContextService.requireCurrentTenantId();
        return userStoryRepository.countByTenantId(tenantId);
    }

    @Transactional(readOnly = true)
    public long countByStatus(UserStory.Status status) {
        Long tenantId = tenantContextService.requireCurrentTenantId();
        return userStoryRepository.countByStatus(tenantId, status);
    }

    @Transactional
    @CacheEvict(value = "userStories", key = "#userStoryId")
    public void saveLatestAnalysis(Long userStoryId, UserStoryDTO.AIAnalysisResponse analysis) {
        UserStory us = findUserStoryForBackgroundUpdate(userStoryId);
        try {
            us.setLatestAnalysisPayload(objectMapper.writeValueAsString(analysis));
        } catch (JsonProcessingException ex) {
            throw new RuntimeException("Failed to serialize analysis payload", ex);
        }
        us.setLatestAnalyzedAt(LocalDateTime.now());
        userStoryRepository.save(us);
    }

    @Transactional(readOnly = true)
    public Optional<LatestAnalysisSnapshot> getLatestAnalysis(Long userStoryId) {
        Long tenantId = tenantContextService.requireCurrentTenantId();
        UserStory us = userStoryRepository.findByIdAndTenantId(userStoryId, tenantId)
                .orElseThrow(() -> new RuntimeException("User Story not found: " + userStoryId));
        if (us.getLatestAnalysisPayload() == null || us.getLatestAnalysisPayload().isBlank()) {
            return Optional.empty();
        }
        try {
            UserStoryDTO.AIAnalysisResponse response = objectMapper.readValue(
                    us.getLatestAnalysisPayload(),
                    UserStoryDTO.AIAnalysisResponse.class
            );
            return Optional.of(new LatestAnalysisSnapshot(response, us.getLatestAnalyzedAt()));
        } catch (Exception ex) {
            log.warn("Failed to parse persisted analysis for userStoryId={}", userStoryId, ex);
            return Optional.empty();
        }
    }

    @Transactional
    @CacheEvict(value = "userStories", key = "#userStoryId")
    public void saveLatestCaseGeneration(Long userStoryId, UserStoryDTO.CaseGenerationSessionDTO session) {
        UserStory us = findUserStoryForBackgroundUpdate(userStoryId);
        try {
            us.setLatestCaseGenerationPayload(objectMapper.writeValueAsString(session));
        } catch (JsonProcessingException ex) {
            throw new RuntimeException("Failed to serialize case generation payload", ex);
        }
        us.setLatestCaseGeneratedAt(LocalDateTime.now());
        userStoryRepository.save(us);
    }

    @Transactional(readOnly = true)
    public Optional<LatestCaseGenerationSnapshot> getLatestCaseGeneration(Long userStoryId) {
        Long tenantId = tenantContextService.requireCurrentTenantId();
        UserStory us = userStoryRepository.findByIdAndTenantId(userStoryId, tenantId)
                .orElseThrow(() -> new RuntimeException("User Story not found: " + userStoryId));
        if (us.getLatestCaseGenerationPayload() == null || us.getLatestCaseGenerationPayload().isBlank()) {
            return Optional.empty();
        }
        try {
            UserStoryDTO.CaseGenerationSessionDTO session = objectMapper.readValue(
                    us.getLatestCaseGenerationPayload(),
                    UserStoryDTO.CaseGenerationSessionDTO.class
            );
            return Optional.of(new LatestCaseGenerationSnapshot(session, us.getLatestCaseGeneratedAt()));
        } catch (Exception ex) {
            log.warn("Failed to parse persisted case generation for userStoryId={}", userStoryId, ex);
            return Optional.empty();
        }
    }

    private UserStoryDTO mapToDTO(UserStory us) {
        Tenant tenant = us.getTenantId() == null ? null : tenantRepository.findById(us.getTenantId()).orElse(null);
        String tenantName = tenant != null ? tenant.getTenantName() : null;
        return UserStoryDTO.builder()
                .id(us.getId())
                .usNumber(us.getUsNumber())
                .title(us.getTitle())
                .description(us.getDescription())
                .acceptanceCriteria(us.getAcceptanceCriteria())
                .priority(us.getPriority())
                .status(us.getStatus())
                .sprint(us.getSprint())
                .epic(us.getEpic())
                .storyPoints(us.getStoryPoints())
                .tenantId(us.getTenantId())
                .tenantCode(tenant != null ? tenant.getTenantCode() : null)
                .tenantName(tenantName)
                .projectName(tenantName)
                .createdBy(mapUserToDTO(us.getCreatedBy()))
                .testCaseCount(us.getTestCases() != null ? us.getTestCases().size() : 0)
                .validationPointCount(us.getValidationPoints() != null ? us.getValidationPoints().size() : 0)
                .validationPoints(us.getValidationPoints() == null ? List.of() : us.getValidationPoints().stream()
                        .map(this::mapValidationPointToDTO)
                        .collect(Collectors.toList()))
                .createdAt(us.getCreatedAt())
                .updatedAt(us.getUpdatedAt())
                .build();
    }

    private UserStoryDTO.ValidationPointItemDTO mapValidationPointToDTO(ValidationPoint point) {
        if (point == null) return null;
        return UserStoryDTO.ValidationPointItemDTO.builder()
                .id(point.getId())
                .description(point.getDescription())
                .expectedResult(point.getExpectedResult())
                .priority(point.getPriority())
                .status(point.getStatus())
                .build();
    }

    private UserDTO mapUserToDTO(User user) {
        if (user == null) return null;
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

    public record LatestAnalysisSnapshot(
            UserStoryDTO.AIAnalysisResponse analysis,
            LocalDateTime analyzedAt
    ) {
    }

    public record LatestCaseGenerationSnapshot(
            UserStoryDTO.CaseGenerationSessionDTO session,
            LocalDateTime generatedAt
    ) {
    }

    private UserStory findUserStoryForBackgroundUpdate(Long userStoryId) {
        return tenantContextService.tryResolveCurrentTenantId()
                .flatMap(tenantId -> userStoryRepository.findByIdAndTenantId(userStoryId, tenantId))
                .orElseGet(() -> userStoryRepository.findById(userStoryId)
                        .orElseThrow(() -> new RuntimeException("User Story not found: " + userStoryId)));
    }
}
